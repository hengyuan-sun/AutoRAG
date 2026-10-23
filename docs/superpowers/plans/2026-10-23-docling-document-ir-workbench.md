# Docling DocumentIR Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the Go/RAGFlow parsing bridge with a Python Docling adapter, preserve the source project’s DocumentIR evidence contract, and let researchers inspect IR and configure which fields each business consumer receives.

**Architecture:** Keep the current FastAPI, Worker, PostgreSQL/pgvector and Vue workbench. Add a versioned DocumentIR package and Docling adapter; derive existing ChunkingBlocks from IR items without flattening away provenance. Persist consumer profiles as versioned workspace resources and expose IR inspection/profile preview APIs used by focused Vue components.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, Docling Python SDK, SQLAlchemy/PostgreSQL, Vue 3/TypeScript, Vitest, Playwright, pytest.

**Spec:** `docs/superpowers/specs/2026-10-23-docling-document-ir-workbench-design.md`

## Global Constraints

- Do not add a Go service, Go build requirement, or RAGFlow runtime dependency.
- Keep the platform’s multipart and raw single-file upload limit at 500 MiB and process uploaded files from disk paths in the parser worker.
- Preserve old local-baseline parse snapshots, Trials, golden evaluation, release activation and rollback behavior.
- Do not invent page numbers, coordinates, OCR success, source spans, or field values that Docling does not provide.
- Keep the complete DocumentIR separate from the IR-to-ChunkingBlock projection and record parser version/config with Trial identity.
- Store Consumer Profile selectors as validated data; never evaluate user-provided Python, templates, or arbitrary expressions.
- Use synthetic fixtures in this repository; do not copy source documents or identifying business data from `D:\公司文件\26年实施项目\02智能审查\documentProcessor`.

## Review Focus

- Unicode and normalized text can make chunk character spans point at the wrong IR item; tests must round-trip exact substrings and item UIDs.
- Docling may omit physical page/layout evidence for some Office documents; tests must preserve null/unsupported status instead of fabricating location.
- Large PDF conversions can exceed memory or lose page order during batching; benchmark a generated 1000-page fixture and verify ordered pages plus measured resource use before claiming large-document support.
- Consumer selectors can expose the wrong field or drop provenance; tests must reject unknown paths and assert every emitted value retains its source UID/location.
- Cached IR and saved Trial/Profile versions can drift after parser or profile changes; tests must prove version/config changes create new snapshots while old releases remain readable.

---

### Task 1: Add and validate the DocumentIR contract

**Files:**
- Create: `src/raglab/document_ir/__init__.py`
- Create: `src/raglab/document_ir/models.py`
- Create: `src/raglab/document_ir/validation.py`
- Test: `tests/test_document_ir_models.py`
- Test: `tests/test_document_ir_validation.py`
- Modify: `readFunction.md`

**Interfaces:**
- `DocumentIR.model_validate(payload)` parses schema-versioned JSON.
- `DocumentIR.model_dump(mode="json")` serializes the canonical object.
- `validate_document_ir(ir: DocumentIR) -> DocumentIR` checks UID uniqueness, valid references, ordered spans, finite coordinates, and table cell indexes without changing values.
- Port the source project’s v1.5 core model field names and enum values for file metadata, engine/config/provider identity, headings, paragraphs, tables/cells, images, formulas, TOC, header/footer, provenance/locations, relations, pages/page records, statuses, warnings, artifacts, shards and manifest metadata. Keep Docling-specific raw extensions under a namespaced extension field rather than altering canonical fields.

- [ ] **Step 1: Write failing schema round-trip tests** named `test_document_ir_v15_round_trips_core_item_kinds` and `test_document_ir_keeps_source_location_and_evidence_status` using synthetic data for every core item kind, locations, table cells, relationships, provider snapshots and page/shard metadata.
- [ ] **Step 2: Run the tests and verify they fail** because `raglab.document_ir` does not exist.
- [ ] **Step 3: Add the Pydantic v2 schema and validators** ported from the reviewed source project, removing imports of parent-project modules.
- [ ] **Step 4: Add failing validation tests** named `test_ir_rejects_duplicate_uid_and_dangling_relation` and `test_ir_rejects_invalid_cell_or_nonfinite_geometry`.
- [ ] **Step 5: Implement validation** with errors that identify the item UID and invalid field.
- [ ] **Step 6: Run** `.venv\Scripts\python.exe -m pytest tests/test_document_ir_models.py tests/test_document_ir_validation.py -q` and require all tests to pass.
- [ ] **Step 7: Commit** the schema, validators, tests and Chinese implementation notes as `feat: add DocumentIR v1.5 contract`.

### Task 2: Implement the Docling adapter and parser identity

**Files:**
- Create: `src/raglab/document_ir/docling_adapter.py`
- Modify: `src/raglab/parsing.py`
- Modify: `src/raglab/config.py`
- Modify: `src/raglab/service.py`
- Modify: `pyproject.toml`
- Modify: `requirements.lock`
- Test: `tests/test_docling_adapter.py`
- Test: `tests/test_parser_presets.py`

**Interfaces:**
- `DoclingParserAdapter.version` returns the locked Docling package version plus adapter version.
- `DoclingParserAdapter.parse(name: str, source_path: Path, revision: str, options: DoclingOptions | None = None) -> DocumentIR` converts a staged source path with a configured `DocumentConverter` and maps DoclingDocument nodes into validated IR. `Lab.parsed` streams BlobStore content to a temporary file in fixed-size blocks, then removes it in `finally`; it never reads the entire upload into memory.
- `DoclingOptions` carries only supported, validated format/pipeline settings, local model-artifact paths, and resource limits; credentials are never serialized into config snapshots.
- `LocalParserAdapter` remains available to read old snapshots and as an explicit compatibility parser; new experiments default to Docling.

- [ ] **Step 1: Write failing adapter tests** `test_docling_adapter_maps_heading_paragraph_table_and_provenance`, `test_docling_adapter_does_not_fabricate_missing_location`, and `test_docling_identity_includes_package_and_pipeline_config`. Inject a small real Docling converter fixture; do not mock the mapping result.
- [ ] **Step 2: Run** `.venv\Scripts\python.exe -m pytest tests/test_docling_adapter.py -q` and confirm failure at import/adapter contract.
- [ ] **Step 3: Resolve a Docling release compatible with Python 3.11 and the workstation**, pin it in `pyproject.toml` and `requirements.lock`, and configure the converter to use local assets only when offline mode is enabled.
- [ ] **Step 4: Implement the adapter** for PDF, DOCX, PPTX, TXT and Markdown. Use deterministic UIDs based on file hash, Docling native item identity/type and deterministic ordinal. Preserve headings, tables/cells, text, page/bbox when supplied, warnings and mapping capability status. Mark unavailable fields without synthetic defaults.
- [ ] **Step 5: Add a generated 1000-page PDF benchmark** named `test_docling_pdf_page_order_and_resource_report`; assert page order and record peak RSS/elapsed time. Enable batching or advertise a page limit only after a correct page-batch mapping is implemented and the target workstation meets the stated resource budget; if it does not, report the measured limit and leave large-document support disabled.
- [ ] **Step 6: Update `Lab.parsed`** to call path-based adapters in a worker thread and key parse snapshots by document hash, parser identity and config digest.
- [ ] **Step 7: Run** `.venv\Scripts\python.exe -m pytest tests/test_docling_adapter.py tests/test_parser_presets.py tests/test_service.py -q`.
- [ ] **Step 8: Commit** the adapter, dependency pin, parser selection and tests as `feat: add Docling parser adapter`.

### Task 3: Project IR items into traceable chunking blocks

**Files:**
- Create: `src/raglab/document_ir/chunk_projection.py`
- Modify: `src/raglab/chunking.py`
- Modify: `src/raglab/service.py`
- Test: `tests/test_ir_chunk_projection.py`
- Modify: `tests/test_chunking.py`
- Modify: `tests/test_metrics.py`

**Interfaces:**
- `to_chunking_document(ir: DocumentIR, document_id: str) -> dict` produces the existing chunker input shape plus IR source references.
- Each projected block contains `id` equal to the stable IR item UID, item type, text, heading path, page/location, table rows/cells and source provenance.
- Every generated Chunk span carries `document_id`, `item_uid`, `[start,end)` Unicode code-point range, and any available page/bbox/cell reference.
- Headings, paragraphs and tables are projectable; image/formula items remain visible in IR and only enter chunk text through an explicit supported text projection.

- [ ] **Step 1: Write failing tests** `test_projection_preserves_ir_uids_and_heading_context`, `test_table_cells_keep_row_column_source_refs`, and `test_chunk_spans_round_trip_to_exact_ir_text`.
- [ ] **Step 2: Run** `.venv\Scripts\python.exe -m pytest tests/test_ir_chunk_projection.py -q` and confirm expected missing projection failures.
- [ ] **Step 3: Implement** the projection and extend `chunk_document` output with the source item/page/cell references while preserving existing span and segment behavior.
- [ ] **Step 4: Update the Trial build path** to chunk the projection, include `DocumentIR.schema_version` and parser config identity in `parse_hashes`/Trial manifest, and reuse the immutable parse snapshot across strategy variants.
- [ ] **Step 5: Run** `.venv\Scripts\python.exe -m pytest tests/test_ir_chunk_projection.py tests/test_chunking.py tests/test_metrics.py tests/test_service.py -q`.
- [ ] **Step 6: Commit** the projection, provenance and regression tests as `feat: project DocumentIR into traceable chunks`.

### Task 4: Persist IR artifacts and expose inspection APIs

**Files:**
- Modify: `src/raglab/service.py`
- Modify: `src/raglab/api.py`
- Modify: `src/raglab/persistence.py`
- Test: `tests/test_document_ir_api.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- `GET /api/v1/documents/{id}/ir?parser=docling` returns IR header, schema/parser identity, item/page counts, capabilities, warnings and manifest; large `items` are not placed in an unbounded response.
- `GET /api/v1/documents/{id}/ir/items?parser=docling&page=1&page_size=100&type=paragraph` returns paginated validated items and preserves the parent IR hash.
- `GET /api/v1/documents/{id}/ir/items/{uid}?parser=docling` returns one item plus linked relations and provenance.
- `GET /api/v1/documents/{id}/parsed` remains compatible for existing callers and derives legacy `blocks` from IR.
- IR payloads are stored as content-addressed JSON artifacts; resource records hold workspace-scoped metadata and artifact references. All reads enforce workspace and document ownership.

- [x] **Step 1: Write failing API tests** `test_ir_api_paginates_items_and_reports_stable_manifest`, `test_ir_item_api_returns_provenance_and_relations`, and `test_ir_api_rejects_cross_workspace_access`.
- [x] **Step 2: Run** `.venv\Scripts\python.exe -m pytest tests/test_document_ir_api.py -q` and verify the missing-route behavior.
- [x] **Step 3: Implement content-addressed IR persistence** with hash verification and JSON encoding; do not inline raw upload bytes or media artifacts in the relational record.
- [x] **Step 4: Implement the workspace-scoped manifest, item-page and item-detail routes** with bounds on page size and response size.
- [x] **Step 5: Preserve and test the existing parsed endpoint response** using an old local-baseline fixture.
- [x] **Step 6: Run** `.venv\Scripts\python.exe -m pytest tests/test_document_ir_api.py tests/test_api.py tests/test_persistence.py -q`.
- [x] **Step 7: Commit** the persisted IR artifacts and inspection routes as `feat: expose persisted DocumentIR inspection API`.

### Task 5: Add versioned Consumer Profiles and preview API

**Files:**
- Create: `src/raglab/document_ir/consumer_profiles.py`
- Modify: `src/raglab/service.py`
- Modify: `src/raglab/api.py`
- Create: `tests/test_consumer_profiles.py`
- Create: `tests/test_consumer_profile_api.py`
- Create: `tests/fixtures/consumer_profiles/retrieval.json`
- Create: `tests/fixtures/consumer_profiles/wps_fields.json`

**Interfaces:**
- `ConsumerField` has `key`, `selector`, `item_types`, `cardinality`, `transform` and `required`; `ConsumerProfile` has `id`, `name`, `version`, `schema_version`, and fields.
- Supported selector grammar is a validated allowlist: `meta.<field>`, `outline[*].<field>`, `items[*].<field>`, `items[*].provenance.<field>`, and `items[*].cells[*].<field>`; no arbitrary JSONPath evaluation.
- Supported transforms are `identity`, `join_text` and `table_markdown`; each output value includes source UID and available location.
- Routes: `GET/POST /api/v1/consumer-profiles`, `GET /api/v1/consumer-profiles/{id}`, `POST /api/v1/documents/{id}/consumer-preview`.
- Experiment requests may include an optional `consumer_profile_id`; its immutable version/hash is copied into Trial data and config hash.

- [ ] **Step 1: Write failing tests** `test_profile_rejects_unknown_selector_and_transform`, `test_profile_preview_emits_source_refs_for_each_value`, and `test_trial_pins_profile_version_and_hash`.
- [ ] **Step 2: Run** `.venv\Scripts\python.exe -m pytest tests/test_consumer_profiles.py -q` and confirm the profile parser/evaluator is absent.
- [ ] **Step 3: Implement profile validation and evaluation** over a validated DocumentIR using explicit traversal; distinguish missing, null, empty and unsupported values.
- [ ] **Step 4: Seed the general retrieval and structured-review profiles** plus a WPS field alias example derived from reviewed `field_dictionary.json` and `procedure_fields.json`; keep source documents and production database writers out of the repository.
- [ ] **Step 5: Implement workspace-scoped profile CRUD and preview routes** and pin profile snapshots in Trials.
- [ ] **Step 6: Run** `.venv\Scripts\python.exe -m pytest tests/test_consumer_profiles.py tests/test_consumer_profile_api.py tests/test_api.py tests/test_service.py -q`.
- [ ] **Step 7: Commit** profile validation, preview, fixtures and tests as `feat: add versioned consumer profiles`.

### Task 6: Build the DocumentIR browser and field-profile editor

**Files:**
- Create: `frontend/src/components/DocumentIRViewer.vue`
- Create: `frontend/src/components/ConsumerProfileEditor.vue`
- Create: `frontend/src/consumerProfiles.ts`
- Create: `frontend/src/consumerProfiles.test.ts`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`
- Modify: `frontend/tests/workbench.spec.ts`

**Interfaces:**
- `DocumentIRViewer` accepts document ID/parser identity, loads the IR manifest and paginated items, filters by type/section/page/status, displays JSON properties and available source location, and emits `selectItem(uid)`.
- `ConsumerProfileEditor` accepts the current IR schema/manifest, creates validated field mappings, requests preview, and displays output plus source UID/location for every value.
- Selecting an IR item from a Chunk navigates to its item and highlights exact source text when spans are available; unavailable visual location is labeled rather than approximated.
- Docling is the default parser option. Keep legacy local snapshots readable; remove the RAGFlow bridge option and diagnostics state.

- [ ] **Step 1: Write failing Vitest tests** `consumerProfiles.test.ts` for field selector validation and output/source metadata display helpers.
- [ ] **Step 2: Run** `pnpm test -- --run src/consumerProfiles.test.ts` and verify module-not-found or expected missing behavior.
- [ ] **Step 3: Implement the helper types and components** with accessibility labels, keyboard-operable tree controls and bounded item pagination.
- [ ] **Step 4: Add Playwright coverage** `workbench.spec.ts`: upload a synthetic PPTX/PDF fixture, run Docling parsing and a chunking experiment, inspect an IR item and source position, choose a business field profile, preview mapped output with provenance, then complete golden evaluation, publish and rollback.
- [ ] **Step 5: Run** `pnpm test`, `pnpm build`, and `pnpm test:e2e` from `frontend`.
- [ ] **Step 6: Commit** the IR workbench UI and browser tests as `feat: add DocumentIR and consumer profile workbench`.

### Task 7: Remove RAGFlow Go bridge and update operational docs

**Files:**
- Delete: `patches/ragflow-parser-bridge/main.go`
- Delete: `scripts/prepare_ragflow.py`
- Modify: `.env.example`
- Modify: `.gitignore` only if an entry becomes obsolete
- Modify: `README.md`
- Modify: `readFunction.md`
- Modify: `docs/development-progress.md`
- Modify: `docs/local-validation.md`
- Modify: `tests/test_parsing_contract.py`
- Modify: `tests/test_parser_presets.py`

**Interfaces:**
- Remove `RAGFLOW_URL`, `RAGFLOW_TOKEN`, `RAGFLOW_REVISION`, bridge probes, and parser health entries.
- Keep adapter diagnostics for Docling version, model asset availability, supported formats, and unavailable optional MineU/MinerU adapters.
- Document model artifact preparation, offline execution, memory/concurrency limits, unsupported features and test commands in Chinese.

- [ ] **Step 1: Write failing diagnostics tests** `test_docling_diagnostics_report_version_and_assets` and `test_unconfigured_optional_parser_is_explicitly_unavailable`.
- [ ] **Step 2: Run** `.venv\Scripts\python.exe -m pytest tests/test_parsing_contract.py tests/test_parser_presets.py -q` and verify old RAGFlow expectations are isolated.
- [ ] **Step 3: Remove RAGFlow-specific settings, bridge source and setup script**, and replace prior RAGFlow contract tests with Docling capability/diagnostic assertions.
- [ ] **Step 4: Update** `readFunction.md`, `README.md`, `docs/development-progress.md` and `docs/local-validation.md`; distinguish passed tests from unavailable capabilities and real-source checks.
- [ ] **Step 5: Run full backend checks** `.venv\Scripts\python.exe -m pytest -q`, `.venv\Scripts\ruff.exe check src tests scripts`, and the real Ollama/PostgreSQL integration test.
- [ ] **Step 6: Run full frontend checks** `pnpm test`, `pnpm build`, and `pnpm test:e2e`.
- [ ] **Step 7: Run** `git diff --check`; review the whole branch diff and push the completed implementation to `origin/feat/rag-lab`.
- [ ] **Step 8: Commit** the bridge removal and final documentation as `refactor: replace RAGFlow bridge with Docling workflow`.

## Plan Self-Review

- Spec coverage: canonical IR and status semantics → Tasks 1–2; source-to-Chunk traceability → Task 3; persistent API inspection → Task 4; business field selection and WPS compatibility sample → Task 5; front-end display and real flow → Task 6; Python-only deployment and docs → Task 7.
- Input/failure coverage: missing coordinates, malformed IR references, table-cell identity, 1000-page page order/resource bounds, invalid profile paths, workspace isolation, stale parser/profile cache keys, and old snapshot compatibility are explicitly assigned tests above.
- Type consistency: all IR routes use the same `DocumentIR`; `to_chunking_document` is the sole IR-to-chunker boundary; Consumer Profile evaluates over the canonical IR and is version-pinned in Trial data.
- Dependency risk: Docling release and PDF model assets are selected and pinned in Task 2 after checking Python 3.11 compatibility and a real local conversion; no live network download is permitted in runtime parsing.
- Acceptance caveat: if Docling cannot meet a tested PDF batching or 1000-page resource limit, the implementation must report the limitation and cannot mark the large-document capability complete by documentation alone.
