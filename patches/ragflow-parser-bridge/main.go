// AutoRAG parser bridge. Compile inside the pinned RAGFlow Go module via build.sh.
package main

import (
    "crypto/subtle"
    "encoding/json"
    "fmt"
    "io"
    "log"
    "net/http"
    "os"
    "path/filepath"
    "strings"
    "time"

    "ragflow/internal/parser/parser"
)

const revision = "e2401e54947db7eb5e542b6de26755d89886f783"
const maxBytes = 500 << 20

type block struct {
    ID string `json:"id"`
    Type string `json:"type"`
    Text string `json:"text"`
    Page *int `json:"page"`
    SectionPath []string `json:"section_path"`
    Rows []string `json:"rows,omitempty"`
    Raw map[string]any `json:"raw,omitempty"`
}

func respond(w http.ResponseWriter, code int, body any) {
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(code)
    _ = json.NewEncoder(w).Encode(body)
}

func serve(token string) http.Handler {
    mux := http.NewServeMux()
    mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
        respond(w, 200, map[string]any{"parser": "ragflow@"+revision, "bridge_version": "1.0"})
    })
    mux.HandleFunc("/internal/v1/parse", func(w http.ResponseWriter, r *http.Request) {
        if r.Method != http.MethodPost { respond(w, 405, map[string]string{"error":"POST required"}); return }
        if subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+token)) != 1 {
            respond(w, 401, map[string]string{"error":"unauthorized"}); return
        }
        r.Body = http.MaxBytesReader(w, r.Body, maxBytes+(1<<20))
        if err := r.ParseMultipartForm(1<<20); err != nil {
            respond(w, 422, map[string]string{"error":"invalid multipart or size limit"}); return
        }
        if r.MultipartForm != nil { defer r.MultipartForm.RemoveAll() }
        file, header, err := r.FormFile("file")
        if err != nil { respond(w, 422, map[string]string{"error":"missing file"}); return }
        defer file.Close()
        data, err := io.ReadAll(io.LimitReader(file, maxBytes+1))
        if err != nil || len(data) == 0 || len(data) > maxBytes {
            respond(w, 422, map[string]string{"error":"empty or oversized file"}); return
        }
        docRevision := r.FormValue("revision")
        if docRevision == "" { respond(w, 422, map[string]string{"error":"missing revision"}); return }
        var producer parser.ParseResultProducer
        switch strings.ToLower(filepath.Ext(header.Filename)) {
        case ".txt": producer = parser.NewTextParser()
        case ".md":
            p, err := parser.NewMarkdownParser(parser.GoMarkdown)
            if err != nil { respond(w, 422, map[string]string{"error":"markdown parser unavailable"}); return }
            p.FetchRemoteImages = false
            producer = p
        case ".docx":
            p := parser.NewDOCXParser()
            p.ConfigureFromSetup(map[string]any{"output_format":"json"})
            producer = p
        case ".pptx": producer = parser.NewPPTXParser()
        case ".pdf":
            p := parser.NewPDFParser()
            // 首轮桥接明确仅启用文本PDF。OCR依赖作为后续配置能力。
            p.ParseMethod = "plain_text"
            producer = p
        default: respond(w, 422, map[string]string{"error":"unsupported file format"}); return
        }
        result := producer.ParseWithResult(r.Context(), header.Filename, data)
        if result.Err != nil {
            log.Printf("parse failed: %v", result.Err)
            respond(w, 422, map[string]string{"error":"ragflow parser failed; inspect bridge log"}); return
        }
        blocks := []block{}
        for _, item := range result.JSON {
            raw := item.ToMap()
            b := block{ID:fmt.Sprintf("b%d",len(blocks)), Type:"text", SectionPath:[]string{}, Raw:raw}
            if text, ok := raw["text"].(string); ok { b.Text = text }
            if table, ok := item.(parser.TableItem); ok && table.Table != nil {
                b.Type = "table"
                for _, row := range table.Table.CellTexts() { b.Rows = append(b.Rows, strings.Join(row," | ")) }
                b.Text = strings.Join(b.Rows,"\n")
                if strings.EqualFold(filepath.Ext(header.Filename),".pdf") { page:=table.Table.Page+1; b.Page=&page }
            }
            // 原始positions透传保留。没有验证语义的页号不凭空映射。
            if strings.TrimSpace(b.Text) != "" { blocks=append(blocks,b) }
        }
        if len(blocks)==0 {
            text := result.Text
            if text=="" { text=result.Markdown }
            if strings.TrimSpace(text)!="" { blocks=append(blocks,block{ID:"b0",Type:"text",Text:text,SectionPath:[]string{}}) }
        }
        if len(blocks)==0 { respond(w,422,map[string]string{"error":"no extracted text"}); return }
        warnings := append(result.Warnings,"bridge: raw source positions retained; unmapped pages are null")
        respond(w,200,map[string]any{"schema_version":1,"revision":docRevision,"parser":"ragflow@"+revision,
                    "bridge_version":"1.0","blocks":blocks,"warnings":warnings})
    })
    return mux
}

func main() {
    token := os.Getenv("RAGLAB_RAGFLOW_TOKEN")
    if token=="" { log.Fatal("RAGLAB_RAGFLOW_TOKEN required") }
    address := os.Getenv("RAGLAB_BRIDGE_ADDR")
    if address=="" { address="127.0.0.1:9388" }
    server := &http.Server{Addr:address, Handler:serve(token), ReadHeaderTimeout:10*time.Second,
                           ReadTimeout:60*time.Second,WriteTimeout:180*time.Second,IdleTimeout:60*time.Second}
    log.Fatal(server.ListenAndServe())
}
