# 开发执行记录

实施依据：RAG试验台复杂度与代码实现方案 v3。

- 当前路径开发，使用feat/rag-lab分支保留origin/main历史。
- 用户已授权提交并推送到hengyuan-sun/AutoRAG。
- 首期模块使用持久化API、真实Ollama和pgvector；纯算法单元测试与外部服务测试分别统计。
- RAGFlow调研提交需要Go1.27及原生依赖；解析适配必须显式报出能力，不能将本地基线冒充RAGFlow。
- 本地数据库已启动，查询确认AGE1.7.0、pgvector0.8.6；只创建独立rag_lab数据库，不修改既有业务表。

## 模块进度

- M1 切分与指标：完成，覆盖5种策略、来源映射和确定性指标。
- M2 持久化与摄入：完成首期，真实PostgreSQL/pgvector和Ollama链路通过。
- M3 实验、检索、黄金集：完成首期，含文档级排名、逐题Trace及结构化导入校验。
- M4 发布回滚与任务：完成首期，包含租约写入fencing、发布门槛及CAS回滚。
- M5 前端、端到端及文档：完成首期，Vitest、Playwright和生产构建通过。
- M6 独立审查与交付：完成，4项评审问题已修复并增加7个回归用例；已提交并推送至`origin/feat/rag-lab`。

## 验证记录（2026-10-22）

- `.venv\\Scripts\\python.exe -m pytest -q --tb=short`：36 passed，1 skipped（真实依赖专项默认跳过）。
- `$env:RAGLAB_RUN_INTEGRATION='1'; .venv\\Scripts\\python.exe -m pytest tests/test_live.py -q --tb=short`：1 passed；本地Ollama、独立PostgreSQL数据库与pgvector真实向量检索、评测、发布、重启后查询均覆盖。
- `frontend\\pnpm test`：1 passed；`frontend\\pnpm build`：Vue类型检查和Vite生产构建通过。
- `frontend\\pnpm test:e2e`：1 passed；真实浏览器操作文件试验、黄金集导入、评测、发布、切换和回滚。
- `.venv\\Scripts\\ruff.exe check src tests scripts`：通过。
- 新增评审回归：7 passed；首轮7失败用于确认缺陷已被测试捕获。

## 评审修复

Worker将job身份放入线程局部作用域。资源写入和向量替换在同一数据库事务锁定任务记录，重新校验owner、fence、RUNNING状态及未过期租约，避免旧Worker的最终状态检查之外继续留下业务结果。

模型绑定按保存的模型名查询Ollama tags，因此模型默认值调整不会影响已经固定到旧digest的索引。检索排名先以所有候选Chunk的分数聚合为文档排名；块级TopK继续单独控制上下文装配。黄金集JSON/CSV都通过共享Pydantic嵌套契约，格式错误返回422并且不落库。
