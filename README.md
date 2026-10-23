# AutoRAG 企业文档研发试验台

面向数据处理研发人员的 Python 文档解析、切分试验、检索评测与版本发布平台。解析使用本地 Docling，控制面与处理网关均为 Python；自建前端展示 DocumentIR 与来源证据，支持研究人员配置业务消费字段。

## 已实现

- TXT、Markdown、DOCX、PPTX、PDF上传与流式接收，单文件默认上限500 MiB。
- Docling DocumentIR 1.5解析、内容寻址产物、分页浏览、来源定位，以及兼容本地解析基线。
- 五种切分预设、最多20组参数扫描、Chunk与IR UID/位置映射。
- 版本化Consumer Profile、白名单字段选择器、字段预览及来源UID/定位。
- PostgreSQL/pgvector、Ollama Embedding、BM25/RRF、黄金集评测、逐题Trace、发布Gate和回滚。
- 预留MineU适配器、OBS和企业文件流接入口；未配置能力在诊断中明确标记。

## 环境与启动

要求Python 3.11+、Node 22+、pnpm、PostgreSQL/pgvector和Ollama。默认Python依赖不安装Docling PDF模型运行时；在线下准备好可信的本地模型资产后，可按需安装可选依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
Copy-Item .env.example .env
# 编辑.env：数据库连接、随机API令牌、Ollama端点/模型和存储路径。
# 可选PDF支持：pip install -e ".[docling-pdf]"；OCR支持：pip install -e ".[docling-ocr]"
# 配置RAGLAB_DOCLING_ARTIFACTS_PATH指向已准备好的本地资产目录。
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
.\.venv\Scripts\python.exe -m uvicorn raglab.api:create_app --factory --host 127.0.0.1 --port 8018
```

Docling运行时强制离线，不会自动从互联网下载模型。DOCX/PPTX/TXT/Markdown无需PDF模型资产；PDF解析依赖本地PDF模型运行时和已准备的资产。OCR默认关闭，需安装可选依赖并在本地明确开启。未知或未就绪的能力会失败并返回说明，不会自动切换解析器。

打开 <http://127.0.0.1:8018>，输入`.env`中的`RAGLAB_API_TOKEN`。开发前端运行`pnpm dev`，Vite代理API至8018。项目工作站可运行`scripts/bootstrap_local.py`，在已存在的`graphrag-postgres-age`容器中创建独立测试数据库和角色；脚本不会重建卷或修改既有GraphRAG业务表。

`.env`、原始文件、生成产物、依赖缓存和外部上游源码均不提交Git。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\python.exe -m pip check
cd frontend
pnpm test
pnpm build
# 先启动8018后端，再运行真实浏览器闭环
pnpm test:e2e
```

单元测试使用隔离SQLite与测试Embedding；真实集成和Playwright使用本地Ollama及PostgreSQL/pgvector。PDF模型资产和扫描件OCR需要单独按目标环境完成验证，不能用文本型PDF结果替代。

## 当前边界

- PDF/OCR与1000页资源上限尚未在本地模型资产环境通过基准验收。
- 精确Token预算、父子/语义切分、公开数据集适配、完整多指标Gate、Milvus备选尚未实现。
- OBS、企业SSO/来源ACL和企业生产文件流仍为预留接口；raw文件流当前使用单机令牌。
- MineU仅在解析器注册契约预留，尚未接入；Reranker未验证，不会默认启用。

完整实现逻辑见[readFunction.md](readFunction.md)，实施设计见[设计说明](docs/superpowers/specs/2026-10-23-docling-document-ir-workbench-design.md)，验证记录见[docs/local-validation.md](docs/local-validation.md)。
