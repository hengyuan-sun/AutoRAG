# 本地环境与源码核对记录

日期：2026-10-22。此记录仅描述实际完成的检查，不等于POC通过。

## RAGFlow

- 官方仓库：https://github.com/infiniflow/ragflow.git
- 本地目录：upstream/ragflow
- 拉取方式：浅克隆默认分支，已成功。
- 调研提交：e2401e54947db7eb5e542b6de26755d89886f783，提交日期2026-10-21。
- 上游源码本体不提交至平台仓库；`scripts/prepare_ragflow.py`会在本机克隆中按固定SHA检查后生成`cmd/raglab-parser/main.go`及构建目标变更，并用标记文件记录。该本机上游目录被Git忽略。
- 已阅读AGENTS.md。当前服务端目标为Go，新增上游功能不应写到旧Python服务端；平台外部Python网关单独维护，不放入上游仓库。
- 已确认解析契约：internal/parser/parser/parse_result.go定义ParseResultProducer.ParseWithResult(ctx, filename, data) ParseResult，结果包含结构化DocItem、文本、元数据和警告。表格/位置字段随解析器不同，仍需真实样本测试。
- 对应路径：internal/parser/parser、internal/ingestion/component、internal/router/router.go、internal/handler/providers.go。路由中已有解析相关入口，但尚未证明可直接满足完整定位导出；不能仅凭名称直接复用。
- internal/engine当前目录包括elasticsearch、infinity、oceanbase、serenedb、vastbase等，未发现专用pgvector或Milvus目录。Vastbase配置存在PG兼容模式，但不据此断言普通PostgreSQL可无修改充当完整引擎。
- 上游默认文档引擎仍为elasticsearch。平台自建pgvector索引不会自动移除RAGFlow原生依赖。
- 上游要求通过build.sh组织Go构建及测试，涉及CGO原生库。已准备桥接源码，但当前工作站没有Go1.27工具链，因此没有完成真实编译或部署。

## Ollama

- 实际服务：127.0.0.1:11436，由OLLAMA_HOST确认；CLI版本0.35.1。
- 模型：qwen3-embedding:0.6b，digest ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d。
- POST /api/embed：两条中文文本，truncate=false，返回2条1024维向量。
- 服务返回total_duration=4988548400纳秒；含加载且样本极小，不作为延迟基线。
- 已安装dengcao/Qwen3-Reranker-0.6B的F16和Q8_0版本；未验证排序协议及分数，不能宣称可用。
- 误用默认11434时模型不存在；通过实际配置11436调用成功。后续配置必须显式固定端点。

## PostgreSQL

- `graphrag-postgres-age`容器已运行；查询确认PostgreSQL17、AGE1.7.0及pgvector0.8.6。
- 脚本创建独立`rag_lab`数据库和随机凭据，没有改动原GraphRAG业务数据库中的表。
- 真实集成测试已通过Ollama向量生成、pgvector写入/余弦检索、黄金评测、版本发布和新Lab实例重新读取查询。该测试是功能验收样本，不是性能基准。

## 后续验证顺序

1. 安装受支持Go工具链并按上游build.sh构建冻结版本，之后以真实RAGFlow解析结果验证桥接。
2. 当前已通过local-baseline解析器与本地Ollama/pgvector完成闭环；RAGFlow适配尚需编译和运行验证。
3. OBS、企业来源连接器、ACL策略、Milvus备选、完整GatePolicy及Token预算仍按后续里程碑实现。
