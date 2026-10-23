<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from './api'
import { sourceSegments } from './sourceView'

type Row = { id: string; data: Record<string, any>; created: number }
const token = ref(sessionStorage.getItem('raglab-token') || '')
const connected = ref(false), busy = ref(false), error = ref(''), notice = ref('')
const page = ref('workbench')
const navigation = [
  { id: 'workbench', label: '文件处理试验', icon: '◫', detail: '解析 · 切分 · 参数扫描' },
  { id: 'evaluation', label: '黄金集与评测', icon: '◎', detail: '证据 · 召回 · 对比' },
  { id: 'release', label: '版本发布', icon: '↗', detail: '验证 · 发布 · 回滚' },
  { id: 'history', label: '实验与诊断', icon: '≋', detail: '历史 · 模型 · 存储' },
]
const kbs = ref<Row[]>([]), kbId = ref(''), documents = ref<Row[]>([]), selectedDocs = ref<string[]>([])
const trials = ref<Row[]>([]), goldenSets = ref<Row[]>([]), evaluations = ref<Row[]>([]), releases = ref<Row[]>([]), experiments = ref<Row[]>([])
const selectedTrial = ref(''), selectedGolden = ref(''), selectedRelease = ref('')
const currentKb = computed(() => kbs.value.find(k => k.id === kbId.value))
const currentTrial = computed(() => trials.value.find(t => t.id === selectedTrial.value))
const filteredTrials = computed(() => trials.value.filter(t => t.data.kb_id === kbId.value && t.data.status === 'READY'))
const filteredGolden = computed(() => goldenSets.value.filter(t => t.data.kb_id === kbId.value))
const filteredReleases = computed(() => releases.value.filter(t => t.data.kb_id === kbId.value))
const filteredEvaluations = computed(() => evaluations.value.filter(e => filteredTrials.value.some(t => t.id === e.data.trial_id)))
const title = computed(() => navigation.find(n => n.id === page.value))
const kbName = ref(''), parser = ref('local'), strategy = ref('recursive'), lengths = ref('400;800'), overlap = ref(50)
const presetList = ref<any[]>([]), chunks = ref<any[]>([]), chunkTotal = ref(0), expandedParsed = ref<any>(null)
const sourceDocument = ref<Row | null>(null), selectedChunk = ref<any>(null)
const activePreset = computed(() => presetList.value.find(p => p.id === strategy.value))
const parsedSlides = computed<number[]>(() => {
  const slides = (expandedParsed.value?.blocks || []).map((block: any): number => block.slide)
    .filter((slide: number) => Number.isInteger(slide))
  return [...new Set<number>(slides)]
})
const locationRanges = (block: any) => selectedChunk.value?.document_id === sourceDocument.value?.id
  ? selectedChunk.value.spans.filter((span: any) => span.block_id === block.id)
  : []
const sourceParts = (block: any) => sourceSegments(block.text, locationRanges(block))
const slideShapeStyle = (block: any) => {
  const position = block.position, size = expandedParsed.value?.slide_size
  if (!position || !size) return {}
  return {left: `${position.left / size.width * 100}%`, top: `${position.top / size.height * 100}%`,
    width: `${position.width / size.width * 100}%`, height: `${position.height / size.height * 100}%`}
}
const query = ref(''), searchMode = ref('hybrid'), budget = ref(2000), topK = ref(5), searchResult = ref<any>(null)
const goldenName = ref('企业黄金集 v1'), goldenJson = ref(''), threshold = ref(.8)
const diagnostics = ref<any>(null), activeJob = ref<any>(null), trace = ref<any>(null)
const uploadInput = ref<HTMLInputElement>(), goldenInput = ref<HTMLInputElement>()
const short = (id: string | null | undefined) => id ? id.slice(0, 8) : '—'
const percent = (v: any) => v === null || v === undefined ? 'N/A' : `${(v * 100).toFixed(1)}%`
const post = (path: string, body: any) => api(path, token.value, { method: 'POST', body: JSON.stringify(body) })

async function action(work: () => Promise<void>) {
  busy.value = true; error.value = ''; notice.value = ''
  try { await work() } catch (e: any) { error.value = e.message || '执行失败' }
  finally { busy.value = false }
}
async function refresh() {
  const [knowledge, ts, gs, es, rs, ex] = await Promise.all([
    api('/knowledge-bases', token.value), api('/records/trial', token.value), api('/records/golden', token.value),
    api('/records/evaluation', token.value), api('/records/release', token.value), api('/records/experiment', token.value),
  ])
  kbs.value = knowledge; trials.value = ts; goldenSets.value = gs; evaluations.value = es; releases.value = rs; experiments.value = ex
  if (!kbId.value && knowledge.length) kbId.value = knowledge[0].id
}
async function connect() {
  await action(async () => {
    await refresh(); connected.value = true; sessionStorage.setItem('raglab-token', token.value)
    presetList.value = await api('/presets', token.value)
    diagnostics.value = await api('/diagnostics', token.value)
    notice.value = '已连接本地研发环境'
  })
}
watch(kbId, async (id) => {
  selectedDocs.value = []; chunks.value = []; searchResult.value = null; expandedParsed.value = null
  selectedTrial.value = ''; selectedGolden.value = ''; selectedRelease.value = ''
  if (id) {
    try {
      const result = await api(`/knowledge-bases/${id}/documents`, token.value)
      if (id === kbId.value) { documents.value = result; selectedDocs.value = result.map((d: Row) => d.id) }
    } catch (e: any) { error.value = e.message }
  }
})
watch(selectedTrial, async (id) => {
  if (id) {
    try {
      const result = await api(`/trials/${id}/chunks`, token.value)
      if (id === selectedTrial.value) { chunks.value = result.items; chunkTotal.value = result.total }
    } catch (e: any) { error.value = e.message }
  }
})
watch(strategy, id => {
  const preset = presetList.value.find(p => p.id === id)
  if (preset) { lengths.value = preset.suggested_lengths.join(';'); overlap.value = preset.overlap }
})
async function createKb() {
  await action(async () => { const kb = await post('/knowledge-bases', { name: kbName.value }); kbName.value = ''; await refresh(); kbId.value = kb.id })
}
async function upload(event: Event) {
  const files = [...((event.target as HTMLInputElement).files || [])]
  await action(async () => {
    for (const file of files) {
      const data = new FormData(); data.append('kb_id', kbId.value); data.append('file', file)
      await api('/ingestions', token.value, { method: 'POST', body: data })
    }
    documents.value = await api(`/knowledge-bases/${kbId.value}/documents`, token.value)
    selectedDocs.value = documents.value.map(d => d.id); notice.value = `已接收 ${files.length} 个文件`
  })
}
async function waitJob(job: any) {
  activeJob.value = job
  const deadline = Date.now() + 15 * 60 * 1000
  while (Date.now() < deadline) {
    const current = await api(`/jobs/${job.id}`, token.value); activeJob.value = current
    if (current.status === 'FAILED') throw new Error(current.error)
    if (current.status === 'SUCCEEDED') return current.result
    await new Promise(r => setTimeout(r, 700))
  }
  throw new Error('等待超过15分钟，可在任务状态中继续查询')
}
async function runExperiment() {
  await action(async () => {
    const variants = lengths.value.split(';').filter(Boolean).map(v => ({strategy: strategy.value, length: Number(v.trim()), overlap: overlap.value}))
    const result = await waitJob(await post('/experiments', {kb_id: kbId.value, document_ids: selectedDocs.value, parser: parser.value, variants}))
    await refresh(); selectedTrial.value = result.trial_ids[0]
    notice.value = result.errors.length ? `部分方案失败：${JSON.stringify(result.errors)}` : `试验完成，共 ${result.trial_ids.length} 个方案`
  })
}
async function preview(doc: Row) {
  await action(async () => {
    selectedChunk.value = null; sourceDocument.value = doc
    expandedParsed.value = await api(`/documents/${doc.id}/parsed?parser=${encodeURIComponent(parser.value)}`, token.value)
  })
}
async function locateChunk(chunk: any) {
  const doc = documents.value.find(item => item.id === chunk.document_id)
  if (!doc) { error.value = 'Chunk对应的文档修订不在当前知识库中'; return }
  const parserId = currentTrial.value?.data.parser || parser.value
  await action(async () => {
    selectedChunk.value = chunk; sourceDocument.value = doc
    expandedParsed.value = await api(`/documents/${doc.id}/parsed?parser=${encodeURIComponent(parserId)}`, token.value)
  })
}
function goldenTemplate() {
  const doc = documents.value[0]
  goldenJson.value = JSON.stringify([{id: 'q1', query: '请填写真实检索问题', relevant_documents: doc ? [doc.id] : []}], null, 2)
}
async function saveGolden() {
  await action(async () => { const g = await post('/golden-datasets', {kb_id: kbId.value, name: goldenName.value, items: JSON.parse(goldenJson.value)}); await refresh(); selectedGolden.value = g.id; notice.value = '黄金集版本已固定' })
}
async function importGolden(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return
  await action(async () => { const f = new FormData(); f.append('kb_id', kbId.value); f.append('name', goldenName.value); f.append('file', file)
    const g = await api('/golden-datasets/import', token.value, {method: 'POST', body: f}); await refresh(); selectedGolden.value = g.id; notice.value = '已导入黄金集' })
}
async function evaluate() {
  await action(async () => { await waitJob(await post('/evaluations', {trial_id: selectedTrial.value, golden_id: selectedGolden.value, mode: searchMode.value, top_k: topK.value, budget: budget.value})); await refresh(); notice.value = '评测完成，逐题结果已保存' })
}
async function search() {
  await action(async () => { searchResult.value = await post('/search', {trial_id: selectedTrial.value, query: query.value, mode: searchMode.value, budget: budget.value, top_k: topK.value}) })
}
async function buildRelease() {
  await action(async () => { const r = await waitJob(await post('/release-builds', {kb_id: kbId.value, trial_id: selectedTrial.value, golden_id: selectedGolden.value, threshold: threshold.value})); await refresh(); selectedRelease.value = r.id; notice.value = r.data.gate.passed ? '完整语料构建与验证通过，可以发布' : '候选版本未通过门槛，请查看评测结果' })
}
async function activate(r: Row) {
  await action(async () => { await post(`/releases/${r.id}/activate`, {expected_release_id: currentKb.value?.data.active_release_id || null}); await refresh(); notice.value = '活动版本已切换；可选择历史版本执行回滚' })
}
function download(value: any, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'}))
  const a = document.createElement('a'); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url)
}
onMounted(() => { if (token.value) connect() })
</script>

<template>
  <div class="layout">
    <aside>
      <div class="brand"><span class="brand-symbol">A</span><div>AutoRAG<small>DOCUMENT RESEARCH LAB</small></div></div>
      <div class="workspace-tag"><span class="green-dot"></span> 本地研发工作区 <span class="subtle">⌄</span></div>
      <div class="nav-label">研发流程</div>
      <nav><button v-for="n in navigation" :key="n.id" :class="{active: page === n.id}" @click="page = n.id"><span class="nav-icon">{{n.icon}}</span><div>{{n.label}}<small>{{n.detail}}</small></div></button></nav>
      <div class="aside-bottom"><span class="green-dot"></span> Local first<small>Ollama · PostgreSQL / pgvector</small><p>让每一次切分改进都有据可查。</p></div>
    </aside>
    <main>
      <header><div class="breadcrumb">研发工作区 <span>/</span> {{title?.label}}</div><div class="header-right"><span class="badge">v0.1 · 本地验证</span><button class="quiet" @click="action(refresh)" :disabled="busy || !connected">↻ 刷新</button></div></header>
      <div class="content">
        <div class="page-heading"><div><div class="eyebrow">AUTORAG / EXPERIMENTS</div><h1>{{title?.label}}</h1><p>从源文档到可发布知识，构建可复现的处理与召回实验。</p></div><div class="status-chip"><span class="green-dot"></span>{{connected ? '环境已连接' : '等待连接'}}</div></div>
        <form v-if="!connected" class="panel login" @submit.prevent="connect"><h2>连接研发环境</h2><p>请输入本地 .env 中的 RAGLAB_API_TOKEN。令牌仅保存在当前浏览器会话。</p><div class="inline"><input v-model="token" type="password" placeholder="访问令牌" aria-label="访问令牌" required><button class="primary" :disabled="busy">连接</button></div></form>
        <template v-else>
          <section class="kb-bar"><label>当前知识库<select v-model="kbId" aria-label="当前知识库"><option value="" disabled>创建或选择知识库</option><option v-for="k in kbs" :value="k.id">{{k.data.name}}</option></select></label><form class="inline" @submit.prevent="createKb"><input v-model="kbName" placeholder="新知识库名称" aria-label="新知识库名称" required maxlength="100"><button :disabled="busy">＋ 新建知识库</button></form></section>
          <div class="stats"><div><span>当前源文件</span><strong>{{documents.length}}<small>份</small></strong><p>独立身份与内容修订</p></div><div><span>可比较方案</span><strong>{{filteredTrials.length}}<small>组</small></strong><p>冻结配置与模型身份</p></div><div><span>黄金集版本</span><strong>{{filteredGolden.length}}<small>版</small></strong><p>可追溯的问题与证据</p></div><div><span>活动发布版本</span><strong class="code">{{short(currentKb?.data.active_release_id)}}</strong><p>验证后切换 · 支持回滚</p></div></div>
          <template v-if="page === 'workbench'">
            <div class="steps"><span class="selected">01 接入源文件</span><i>→</i><span>02 配置处理策略</span><i>→</i><span>03 运行与比较</span></div>
            <div class="two-columns">
              <section class="panel"><div class="panel-heading"><h2>源文件</h2><span class="badge">{{selectedDocs.length}} 个已选</span></div><input ref="uploadInput" type="file" hidden multiple accept=".txt,.md,.docx,.pptx,.pdf" @change="upload"><button class="drop-zone" :disabled="busy || !kbId" @click="uploadInput?.click()"><span>↑</span><strong>选择文件上传</strong><small>PDF · DOCX · PPTX · TXT · Markdown，单文件最大 500 MiB</small></button>
                <div class="file-list"><div v-for="d in documents" :key="d.id" class="file-row"><input type="checkbox" v-model="selectedDocs" :value="d.id" :aria-label="`选择${d.data.name}`"><span class="file-icon">▤</span><div><strong>{{d.data.name}}</strong><small :title="d.id">文档 {{short(d.id)}} · {{short(d.data.hash)}}</small></div><button class="quiet" @click="preview(d)" :disabled="busy">预览</button></div><p v-if="!documents.length" class="empty">先创建知识库，再上传第一份研发文件。</p></div>
              </section>
              <section class="panel"><div class="panel-heading"><h2>处理策略</h2><span class="badge">参数扫描</span></div><label>解析器<select v-model="parser" aria-label="解析器"><option value="local">本地解析 · DOCX / PPTX / 文本PDF / TXT / MD</option><option value="ragflow" :disabled="!diagnostics?.parsers.ragflow_available">RAGFlow Go 解析桥接{{diagnostics?.parsers.ragflow_available ? ' · 在线' : '（未检测到定版桥接）'}}</option></select></label><label>切分策略预设<select v-model="strategy" aria-label="切分预设"><option v-for="p in presetList" :value="p.id">{{p.name}}</option></select></label><div class="inline fields"><label>{{activePreset?.length_label || '单块最大长度（字符）'}}<input v-model="lengths" aria-label="切分长度" :placeholder="activePreset?.suggested_lengths.join(';')"></label><label v-if="activePreset?.overlap_supported !== false">重叠字符<input v-model.number="overlap" type="number" min="0" max="1599" aria-label="重叠字符"></label><label v-else>重叠字符<input :value="0" aria-label="重叠字符" disabled></label></div><div class="info">解析器只负责抽取文档结构；切分策略在解析块上运行。{{activePreset?.length_semantics}}。分号分隔长度用于对照，最多20组；字符位置可回到原文。</div><button class="primary full" :disabled="busy || !selectedDocs.length" @click="runExperiment">{{busy ? '正在执行任务…' : '▶ 运行处理试验'}}</button></section>
            </div>
            <section v-if="expandedParsed" class="panel source-viewer"><div class="panel-heading"><h2>原文定位 · {{sourceDocument?.data.name}}</h2><span class="badge">{{expandedParsed.parser}}</span><button class="quiet" @click="expandedParsed = null; selectedChunk = null">关闭</button></div><div class="info">{{expandedParsed.slide_size ? '按原幻灯片比例和文本框位置渲染；图片及主题装饰不包含在本地解析视图中。' : '按解析器提取顺序呈现原文结构。'}}{{selectedChunk ? '高亮对应当前 Chunk 的精确字符区间。' : '运行切分后可点击 Chunk 定位其原文。'}}{{expandedParsed.warnings?.join('；')}}</div><div v-if="expandedParsed.slide_size" class="slide-list"><section v-for="slide in parsedSlides" :key="slide" class="slide-frame" :style="{aspectRatio: `${expandedParsed.slide_size.width}/${expandedParsed.slide_size.height}`}"><div class="slide-label">第 {{slide}} 张幻灯片</div><article v-for="b in expandedParsed.blocks.filter((block:any) => block.slide === slide)" :id="`source-${b.id}`" class="slide-shape" :style="slideShapeStyle(b)"><small>{{b.shape_name}}</small><pre><template v-for="(part, index) in sourceParts(b)" :key="index"><mark v-if="part.marked">{{part.text}}</mark><template v-else>{{part.text}}</template></template></pre></article></section></div><div v-else class="source-blocks"><article v-for="b in expandedParsed.blocks" :id="`source-${b.id}`" class="source-block"><div class="chunk-meta">{{b.id}} · {{b.type}} · {{b.page ? `第${b.page}页` : '段落定位'}}</div><pre><template v-for="(part, index) in sourceParts(b)" :key="index"><mark v-if="part.marked">{{part.text}}</mark><template v-else>{{part.text}}</template></template></pre></article></div></section>
            <section class="panel"><div class="panel-heading"><h2>试验结果与 Chunk 预览</h2><select v-model="selectedTrial" aria-label="试验方案"><option value="">选择已完成方案</option><option v-for="t in filteredTrials" :value="t.id">{{short(t.id)}} · {{t.data.config.strategy}} / {{t.data.config.length}} / {{t.data.config.overlap}}</option></select><button class="quiet" :disabled="!currentTrial" @click="download(currentTrial, 'trial.json')">导出配置</button></div><div v-if="currentTrial" class="result-summary"><b>{{chunkTotal}} 个片段</b><span>平均 {{Math.round(currentTrial.data.average_length)}} 字符</span><span>{{currentTrial.data.parser === 'local' ? '本地基线' : 'RAGFlow'}} · {{short(currentTrial.data.model_binding.digest)}}</span></div><div class="chunk-grid"><article v-for="(c, i) in chunks" :key="c.id"><div class="chunk-meta">CHUNK {{String(i+1).padStart(2,'0')}} <span>{{c.text.length}} 字符 · {{c.slide ? `第${c.slide}张幻灯片` : c.page ? `第${c.page}页` : '段落定位'}}</span></div><pre>{{c.text}}</pre><small class="subtle">{{c.spans.map((s:any) => `${s.block_id}[${s.start},${s.end})`).join(' · ')}}</small><button class="quiet locate-button" :aria-label="`定位Chunk ${String(i+1).padStart(2,'0')}原文`" @click="locateChunk(c)">⌖ 定位原文</button><p v-if="c.warnings.length" class="warning">{{c.warnings.join('；')}}</p></article></div><p v-if="!chunks.length" class="empty">运行试验后，可在这里比较配置并查看每个片段的原文位置。</p><small v-if="chunkTotal > chunks.length" class="subtle">展示前 {{chunks.length}} 个片段，共 {{chunkTotal}} 个，可通过分页API读取其余片段。</small></section>
          </template>
          <template v-if="page === 'evaluation'">
            <div class="two-columns"><section class="panel"><div class="panel-heading"><h2>黄金集管理</h2><button class="quiet" @click="goldenTemplate">填入模板</button></div><label>版本名称<input v-model="goldenName" aria-label="黄金集名称"></label><label>问题与相关文档 JSON<textarea v-model="goldenJson" rows="9" aria-label="黄金集JSON" placeholder='[{"id":"q1","query":"检索问题","relevant_documents":["文档ID"]}]'></textarea></label><div class="inline"><button class="primary" :disabled="busy || !kbId" @click="saveGolden">保存黄金集</button><input ref="goldenInput" type="file" hidden accept=".json,.csv" @change="importGolden"><button :disabled="busy || !kbId" @click="goldenInput?.click()">导入 JSON / CSV</button></div><p class="subtle">精确证据可增加 evidence 数组；没有证据标签的指标显示 N/A。</p></section>
              <section class="panel"><h2>召回验证</h2><label>试验方案<select v-model="selectedTrial" aria-label="评测方案"><option value="">选择方案</option><option v-for="t in filteredTrials" :value="t.id">{{short(t.id)}} · {{t.data.config.strategy}} / {{t.data.config.length}}</option></select></label><label>黄金集<select v-model="selectedGolden" aria-label="评测黄金集"><option value="">选择黄金集版本</option><option v-for="g in filteredGolden" :value="g.id">{{g.data.name}} · {{g.data.items.length}}题</option></select></label><div class="inline fields"><label>检索模式<select v-model="searchMode"><option value="vector">向量检索</option><option value="bm25">中文 BM25</option><option value="hybrid">向量 + BM25 / RRF</option></select></label><label>Top K<input v-model.number="topK" type="number" min="1" max="50"></label></div><label>实际上下文字符预算<input v-model.number="budget" type="number" min="1" max="20000"></label><button class="primary full" :disabled="busy || !selectedTrial || !selectedGolden" @click="evaluate">运行黄金集评测</button></section></div>
            <section class="panel"><h2>指标对比</h2><div class="table-wrap"><table><thead><tr><th>方案 / 评测</th><th>Recall</th><th>Hit</th><th>MRR</th><th>证据召回</th><th>证据精度</th><th>IoU</th><th>P95</th><th>错误率</th><th></th></tr></thead><tbody><tr v-for="e in filteredEvaluations"><td>{{short(e.data.trial_id)}}<small>{{short(e.id)}} · {{e.data.total}}题</small></td><td>{{percent(e.data.metrics.recall)}}</td><td>{{percent(e.data.metrics.hit)}}</td><td>{{percent(e.data.metrics.mrr)}}</td><td>{{percent(e.data.metrics.evidence_recall)}}</td><td>{{percent(e.data.metrics.evidence_precision)}}</td><td>{{percent(e.data.metrics.evidence_iou)}}</td><td>{{e.data.metrics.p95_ms?.toFixed(0)}}ms</td><td>{{percent(e.data.metrics.error_rate)}}</td><td><button @click="trace = e.data">逐题</button></td></tr></tbody></table></div><p v-if="!filteredEvaluations.length" class="empty">还没有评测记录。选择方案和黄金集开始比较。</p></section>
            <section class="panel"><h2>单条检索调试</h2><form class="inline" @submit.prevent="search"><input v-model="query" aria-label="检索问题" placeholder="输入业务问题，查看真实召回和原文证据" required><button class="primary" :disabled="busy || !selectedTrial">检索</button></form><template v-if="searchResult"><div class="result-summary"><b>{{searchResult.hits.length}} 条命中</b><span>{{searchResult.latency_ms.toFixed(0)}} ms</span><span>实际上下文 {{searchResult.context.cost}} 字符</span></div><article v-for="h in searchResult.hits" class="search-hit"><div class="chunk-meta">文档 {{short(h.document_id)}} · 分数 {{h.score.toFixed(4)}}</div><pre>{{h.text}}</pre></article></template></section>
            <section v-if="trace" class="panel"><div class="panel-heading"><h2>逐题结果与来源</h2><button @click="download(trace,'evaluation.json')">导出报告</button><button class="quiet" @click="trace = null">关闭</button></div><article v-for="item in trace.items" class="search-hit"><b>{{item.query_id}} · {{item.query}}</b><p>Recall {{percent(item.metrics.recall)}} · 证据召回 {{percent(item.metrics.evidence_recall)}}</p><p v-if="item.error" class="warning">{{item.error}}</p><pre>{{item.trace?.context.text || '没有上下文'}}</pre><details><summary>来源与完整调用链</summary><pre>{{JSON.stringify(item.trace,null,2)}}</pre></details></article></section>
          </template>
          <template v-if="page === 'release'">
            <section class="panel"><h2>构建完整知识库候选版本</h2><p class="subtle">使用选定策略处理当前全部源文件，执行固定黄金集验证，最后由你切换活动版本。</p><div class="inline fields"><label>来源试验<select v-model="selectedTrial" aria-label="发布方案"><option value="">选择已完成方案</option><option v-for="t in filteredTrials" :value="t.id">{{short(t.id)}} · {{t.data.config.strategy}} / {{t.data.config.length}}</option></select></label><label>验证黄金集<select v-model="selectedGolden" aria-label="发布黄金集"><option value="">选择版本</option><option v-for="g in filteredGolden" :value="g.id">{{g.data.name}}</option></select></label><label>文档Recall门槛<input v-model.number="threshold" type="number" min="0" max="1" step="0.05"></label><button class="primary" :disabled="busy || !selectedTrial || !selectedGolden" @click="buildRelease">构建并验证</button></div></section>
            <section class="panel"><h2>发布版本与回滚</h2><div class="release-grid"><article v-for="r in filteredReleases" class="release-card"><span class="badge" :class="r.data.gate.passed ? 'success' : 'danger'">{{currentKb?.data.active_release_id === r.id ? '活动版本' : r.data.gate.passed ? '验证通过' : '验证未通过'}}</span><h3>{{short(r.id)}}</h3><p>Recall {{percent(r.data.gate.metrics.recall)}} · 错误率 {{percent(r.data.gate.metrics.error_rate)}}</p><small>模型 {{short(r.data.model_binding.digest)}}<br>manifest {{short(r.data.manifest_hash)}}</small><div class="inline"><button class="primary" :disabled="busy || !r.data.gate.passed || currentKb?.data.active_release_id === r.id" @click="activate(r)">{{currentKb?.data.active_release_id ? '切换到此版本 / 回滚' : '发布此版本'}}</button><button @click="download(r,'release.json')">导出</button></div></article></div><p v-if="!filteredReleases.length" class="empty">完整构建完成后，候选版本会显示在这里。</p></section>
          </template>
          <template v-if="page === 'history'">
            <section class="panel"><div class="panel-heading"><h2>本地环境能力</h2><button @click="action(async () => { diagnostics = await api('/diagnostics', token) })">重新探测</button></div><div class="capabilities"><div><b>向量存储</b><span>{{diagnostics?.database}}</span></div><div><b>Embedding</b><span>{{diagnostics?.model.model}} · {{diagnostics?.model.available ? '可连接' : '不可连接'}}</span></div><div><b>RAGFlow</b><span>{{diagnostics?.parsers.ragflow_configured ? '已配置桥接，需真实验证' : '未配置；本地基线可用'}}</span></div><div><b>扩展能力</b><span>Token预算、Reranker、OBS连接器：尚未启用</span></div></div></section>
            <section class="panel"><h2>实验历史</h2><div class="table-wrap"><table><thead><tr><th>实验</th><th>解析器</th><th>文件</th><th>完成方案</th><th>状态</th><th>时间</th><th></th></tr></thead><tbody><tr v-for="e in experiments.filter(e => e.data.kb_id === kbId)"><td>{{short(e.id)}}</td><td>{{e.data.parser}}</td><td>{{e.data.document_ids.length}}</td><td>{{e.data.trial_ids?.length || 0}}</td><td>{{e.data.status}}</td><td>{{new Date(e.created*1000).toLocaleString('zh-CN')}}</td><td><button @click="download(e,'experiment.json')">导出</button></td></tr></tbody></table></div></section>
          </template>
        </template>
        <div v-if="activeJob && busy" class="job-bar" role="status"><span class="spinner"></span><b>{{activeJob.kind}}</b><span>{{short(activeJob.id)}} · {{activeJob.status}} · 已接受任务，请等待真实处理完成</span></div>
        <div v-if="notice" class="toast success" role="status">✓ {{notice}}</div><div v-if="error" class="toast danger" role="alert">{{error}}<button class="quiet" @click="error = ''">×</button></div>
        <footer>AutoRAG 研发试验台 <span>配置可复现 · 证据可追溯 · 版本可回滚</span></footer>
      </div>
    </main>
  </div>
</template>
