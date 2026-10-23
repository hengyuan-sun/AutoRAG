# 本地环境与源码核对记录

日期：2026-10-23。本文记录已实际执行的本地检查；未配置的PDF模型能力仍需独立验收。

## Docling解析

- Python解析与API网关统一使用Docling SDK，依赖锁定`docling-slim==2.142.0`，运行离线且不会自动下载模型。
- 已通过合成DOCX、PPTX、TXT和Markdown的DocumentIR转换、schema校验和浏览器端到端。
- PDF适配要求`docling-pdf`可选依赖与`RAGLAB_DOCLING_ARTIFACTS_PATH`本地资产目录。目前工作站尚未完成PDF模型运行时和资产配置，因此扫描PDF、OCR及1000页资源上限没有通过真实样本验收。
- 前端诊断显示SDK版本、格式、PDF运行时/资产状态、OCR选项和MineU预留状态；缺少PDF能力时解析失败并提示，不自动联网或切换解析器。

## Ollama

- 实际服务：127.0.0.1:11436，由OLLAMA_HOST确认；CLI版本0.35.1。
- 模型：qwen3-embedding:0.6b，已验证`/api/embed`返回1024维向量。
- 已安装Reranker模型，但排序协议和分数未验证；当前产品不启用Reranker。
- 使用配置端点11436；默认11434不保证存在同一模型。

## PostgreSQL

- `graphrag-postgres-age`容器正在运行；曾查询确认PostgreSQL17、AGE1.7.0和pgvector0.8.6。
- 平台使用独立`rag_lab`数据库，没有修改既有GraphRAG业务数据库中的表。
- 真实集成覆盖Ollama向量生成、pgvector写入/余弦检索、黄金评测、版本发布和重启后查询；该用例不是性能基准。

## 验证范围

- `.venv\\Scripts\\python.exe -m pytest -q`覆盖隔离SQLite和本地解析；PDF模型资源与超大文档基准用例仍会在缺少资产时跳过。
- `frontend/pnpm test`和`pnpm build`验证浏览器辅助逻辑与生产构建。
- Playwright合成PPTX流程覆盖Docling解析、DocumentIR来源浏览、Consumer Profile创建/预览、黄金评测、发布和回滚。
- 旧版Go解析桥接尝试未完成编译/服务验收，现已从代码、配置、运行步骤和诊断中移除；当前执行路径不需要Go。

OBS企业连接器、来源ACL、Milvus备选、完整GatePolicy、Token预算和通用DAG仍按后续里程碑实现。
- 真实集成：`RAGLAB_RUN_INTEGRATION=1 .venv/Scripts/python.exe -m pytest tests/test_live.py -q`，1 passed，使用本地Ollama和隔离PostgreSQL/pgvector库。
