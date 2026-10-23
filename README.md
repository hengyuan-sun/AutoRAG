# AutoRAG 企业文档研发试验台

面向数据处理研发人员的本地平台：上传文档、配置切分预设、比较召回效果、构建并发布完整知识库版本。

首期技术栈：Vue 3 / TypeScript、FastAPI、PostgreSQL + pgvector、Ollama。
RAGFlow采用冻结Go源码的独立解析桥接；当前交付包含桥接源码及可复现准备脚本，原生运行尚未验证。

## 已实现

- TXT、Markdown、DOCX、文本PDF、PPTX摄入和流式接收，单文件默认上限500 MiB，文档身份/内容修订和幂等冲突检查。
- 本地基线解析与显式RAGFlow桥接适配；未配置RAGFlow时不静默降级。
- 递归、滑动窗口、标题条款、FAQ、表格行组五种切分预设；参数标签随策略切换。支持文本原文定位、高亮和PPTX文本框位置展示。
- 持久化任务、Worker租约/心跳、解析和Embedding缓存、最多20组参数扫描。
- 真实Ollama Embedding，按模型digest绑定索引；pgvector精确检索、中文BM25及RRF融合。
- JSON/CSV黄金集、逐题Trace、文档Recall/Hit/MRR/nDCG和证据Recall/Precision/IoU。
- 完整语料候选构建、黄金集Gate、CAS发布与历史回滚、跨服务重建后的持久查询。
- 中文研发前端、管理员/只读令牌、配置及报告导出。

## 运行

要求Python 3.11+、Node 22+、pnpm、已有PostgreSQL/pgvector与Ollama。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
Copy-Item .env.example .env
# 编辑.env：数据库连接、随机API令牌、实际Ollama端点与模型。
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
.\.venv\Scripts\python.exe -m uvicorn raglab.api:create_app --factory --host 127.0.0.1 --port 8018
```

打开 <http://127.0.0.1:8018>，在连接页输入本地`.env`里的`RAGLAB_API_TOKEN`。
开发前端运行`pnpm dev`，访问5173，Vite代理API到8018。后端启动时若存在frontend/dist，会同时提供静态界面。

本项目工作站可运行`scripts/bootstrap_local.py`，在已有`graphrag-postgres-age`容器中创建随机命名的隔离数据库和角色。
脚本不会重建卷或修改已有GraphRAG表；通用环境请自行配置连接，不必使用此专用脚本。
`.env`、原始文件、生成产物、依赖缓存和上游源码均不提交Git。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests -m "not integration" -q
$env:RAGLAB_RUN_INTEGRATION='1'
.\.venv\Scripts\python.exe -m pytest tests/test_live.py -q
Remove-Item Env:RAGLAB_RUN_INTEGRATION
.\.venv\Scripts\python.exe -m ruff check src tests
cd frontend
pnpm test
pnpm build
# 先在另一个终端启动8018后端；测试使用本机Edge和真实Ollama/pgvector。
pnpm test:e2e
```

单元测试使用独立SQLite及测试Embedding，仅用于领域隔离验证；真实集成与浏览器测试使用实际Ollama/pgvector。
两类结果分别统计。集成测试会在专用库创建测试工作区；浏览器测试会在local工作区创建带时间戳的测试知识库。

## RAGFlow Go桥接

```powershell
.\.venv\Scripts\python.exe scripts/prepare_ragflow.py
```

脚本锁定官方提交`e2401e54947db7eb5e542b6de26755d89886f783`，将`patches/ragflow-parser-bridge/main.go`
放入上游Go模块并定向原build.sh构建目标。未提交的上游改动会导致脚本拒绝覆盖。
在符合上游AGENTS.md要求、具备Go 1.27及CGO原生库的Linux环境完成依赖准备后：

```bash
cd upstream/ragflow
bash build.sh --go
export RAGLAB_RAGFLOW_TOKEN='your-separate-bridge-token'
./bin/raglab_parser
```

随后配置网关的`RAGLAB_RAGFLOW_URL`和`RAGLAB_RAGFLOW_TOKEN`，在前端显式选择RAGFlow。
桥接首轮PDF模式为plain_text，未宣称完成OCR或复杂PDF结构验证。

## 当前边界

- 精确Token预算、父子/语义切分、OCR、自动下载公开基准适配器、Milvus备用实现待后续完成。
- 当前预算为Unicode字符，界面明确显示字符；没有伪造Token计数。
- 黄金集支持自有统一JSON/CSV；公开基准需要先转换和核验标签/许可。
- OBS、企业SSO/来源ACL与企业生产接入只预留契约；raw上传是单机令牌下的通用文件流入口。
- 模型/RAGFlow/数据库连接故障明确显示错误；未验证的Reranker默认不启用。
- 首期Gate按文档Recall及执行错误率验证，尚未实现完整v3相对基线和多指标Gate策略。

完整实现逻辑见[readFunction.md](readFunction.md)，开发证据见[docs/development-progress.md](docs/development-progress.md)。
本地运行状态与原始调研文档属于先前观察，不代表当前全部能力完成。
