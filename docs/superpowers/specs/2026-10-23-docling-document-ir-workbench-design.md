# Docling 与 DocumentIR 工作台设计

## 目标

试验台的解析、切分、评测和发布主链由 Python 实现，不运行或构建 Go 服务，不再依赖 RAGFlow。以 Docling 作为可替换的 Python 文档解析引擎，将解析结果归一成可持久化、可追溯、可视化的 DocumentIR；保留当前五类切分、黄金集评测、版本发布、500 MiB 上传及未来 MineU 适配能力。研发人员可在前端检查解析对象，并按业务场景定义需要消费的 IR 字段及输出名称。

## 既有解析项目核对

源项目位于 `D:\公司文件\26年实施项目\02智能审查\documentProcessor`，当前 IR schema 为 1.5。核心契约包含：

- 文件元数据、解析引擎身份和版本、章节树、目录、页眉页脚、段落、表格及单元格、图片、公式、关系边、警告和能力状态。
- 每项内容的稳定 UID、章节路径、来源文本区间、页码、bbox/多边形、表格行列位置、证据引用和状态；PageRecord 记录处理结果、provider 调用和原因。
- provider/config 快照、原件/派生件引用、结果分片和 manifest，供审计、复现及大文档结果读取。
- 受理、格式探测和归一；PDF/DOCX 解析；可选 MinerU、加密/DLP/旧 DOC 转换、富化、任务状态/取消/checkpoint、结果质量门和业务投影。
- WPS 场景包含字段别名、字段抽取、证据和质量问题，以及 PDF/DOCX/知识库的消费投影。

迁移边界：旧 DOCX 引擎导入父项目 `service.doc_impl.parse_docx.ParseDocx`，部分投影也依赖父项目 `util`；旧项目不是可直接安装的独立解析包。因此迁移 IR/业务契约和必要算法，不把父项目内核或数据库写入代码整体复制到试验台。旧项目文档还明确：PaddleOCR provider 尚未进入 PDF 页面分派主链，旧分页设施不意味着所有引擎都常量内存流式；不得把未接通能力标为已支持。

## 架构决策

### 解析链

新增 `DoclingParserAdapter`，由本地 Python Docling SDK 解析路径文件。模型资产路径和 OCR/表格选项通过配置传入；生产解析在 Worker 中执行，上传仍由试验台流式接收到 BlobStore，解析器接收临时文件路径，避免将 500 MiB 文件整体复制到内存。结果记录 Docling 包版本、pipeline 配置摘要、耗时、警告和能力执行状态；缓存键包括内容 hash、Docling 版本和解析配置 hash。

适配器将 Docling 结构映射到 DocumentIR，不伪造 Docling 未提供的物理页、bbox、OCR 成功状态或源偏移。不能可靠映射的属性设置为 null 或相应的 `unsupported`/`unresolved` 状态并带原因。保留原始上传文件 hash 与受限 artifact 引用；大型原始 payload 不内联到 IR。

PDF/DOCX/PPTX/TXT/Markdown 为首期格式；实际可用格式以锁定版本和测试样本为准。Docling 输入支持及资源成本须通过本地样本验证。旧 DOC 转换、加密文件、DLP 和 MinerU 不因换引擎而被默认为已迁移：首期明确哪些能力沿用现有 Python 组件，哪些报告为未支持/预留。MineU/MinerU 及未来解析器通过同一 adapter 接口注册，不进入主链必需依赖。

### DocumentIR 与切分

工作台保存 canonical DocumentIR，并保留 IR 的 schema version。新增的 `IR → ChunkingBlock` 投影只选择标题、段落、表格等适合切分的节点；完整 IR 不被扁平文本替换。Chunk 保存 DocumentIR item UID、文档修订、字符区间以及可用页/坐标/单元格引用，使现有五种切分和证据评测继续运行。解析器版本和 pipeline 配置随 Trial 固化；改变切分策略不重新解析文档。

通过 DocumentIR 加法字段和显式 schema 版本迁移处理旧数据。已有 local-baseline 结果须仍能读取；解析器升级不得改变其已保存的历史 Trial/Release。

### IR 可视化和业务消费字段

前端提供 IR 树视图和原文/页面来源视图：按 item 类型、章节、页、状态筛选；选择 item 显示 JSON 属性、来源坐标、字符区间、表格 cell 和 warnings；可以从 Chunk 跳回 item。原文无法获得精确页面渲染时展示结构化内容和可用的 bbox overlay，并明确标识定位精度，不能伪装为原页像素级预览。

新增版本化 Consumer Profile：从当前 DocumentIR schema 中选择允许消费的字段，设置目标业务字段名、节点类型过滤、单值/多值及安全的内置转换；配置保存为 JSON，不执行 Python、模板代码或任意表达式。Profile 试运行输出可预览，并同时展示每个值的 source UID/位置引用。Trial 固定 Profile 版本和 hash；不同场景的选择不会修改 canonical IR。

内置 profile 提供“检索摄入”和“结构化审阅”两种通用模板。基于旧项目的 WPS `field_dictionary.json`、`procedure_fields.json` 及已提交 golden 样本提供一个可选示例模板/兼容核验样本；生产数据库写入、业务审批和原项目父级 DOCX 内核不迁入本平台首期。

### 兼容与部署

首期平台 Python 运行依赖为 FastAPI、Docling、现有 SQLAlchemy/PostgreSQL/pgvector。移除 RAGFlow 专用 Go bridge、Go 准备脚本和前端 RAGFlow Go parser 选项。保留通用 `ParserAdapter` 接口与 MineU/MinerU 占位配置，但未实现的 adapter 显示 unavailable。

现有默认 500 MiB 单文件接收能力保留。上传大小、解析进程并发、超时、临时磁盘和 artifact 上限分别配置。PDF 的分页/分片策略需先验证 Docling 在目标样本上的可行性；若其单次转换无法满足 1000 页内存/恢复门槛，不宣称旧项目的 checkpoint 能力已经保留，必须以页面批次/分片实现并通过验收后才打开该能力。

## 验收标准

1. 锁定 Docling 依赖和离线模型资源后，中文 PDF、DOCX、PPTX、TXT、Markdown 样本可解析并通过 DocumentIR schema 校验；扫描 PDF 和表格样本显式验证 OCR/表格质量与定位状态。
2. 同一文件及同一解析配置产生稳定 item UID 与缓存身份；变更文件 hash、Docling 版本或解析配置会产生新解析快照。
3. 解析 IR 可由 API 读取、分页/按类型筛选并在前端检查；点选 item 和 Chunk 能显示对应文本与可用原文定位。未提供的页码/bbox 必须显式缺失。
4. Consumer Profile 可保存、版本化、预览和绑定 Trial；非法/越权字段路径、未知 IR schema、未支持转换均被拒绝；每个消费字段保留来源证据。
5. 五种切分、黄金集指标、发布/回滚闭环保持通过；IR 的段落/表格投影覆盖原始 Chunk 来源区间。
6. 500 MiB 配置边界仍由流式上传层检查，拒绝超限文件而不落成功资源；解析任务不会把整个文件内容额外复制进内存。
7. `documentProcessor` 已有可复用的 WPS、PDF、DOCX golden/fixture 用于核验兼容差异；不能逐项相同时，差异进入报告并标明由 Docling 引擎变化带来，不更新 golden 来掩盖差异。
8. 任何宣称支持的 1000 页、OCR、加密、DOC 转换和恢复行为都需要独立真实样本验收；未达门槛显示降级或暂不支持。

## 非目标

本阶段不部署 RAGFlow、不编译或运行 Go 服务、不实现 MineU/MinerU 新接入、WPS 生产数据库写入、企业文件连接器/OBS、OCR 模型训练或任意业务脚本沙箱。Docling 在 PDF 上使用的模型资产及 CPU/GPU 预算需独立评估和锁定。

## 拟实施分块

1. 锁定 Docling 版本、模型配置及代表性 PDF/DOCX/PPTX 样本，建立 IR 映射对照测试。
2. 移入 DocumentIR 核心 schema/校验与 adapter 契约，替换解析实现并保留旧结果读取。
3. 建立 DocumentIR 到现有切分块的投影和 provenance 回链，确保现有实验、评测和发布测试继续通过。
4. 持久化版本化 Consumer Profile 与 API，并加入字段选择/转换测试和旧 WPS 字段 preset 样本。
5. 构建 IR 浏览器、原文定位和消费字段配置/预览界面，补足浏览器端到端闭环。
6. 移除 RAGFlow Go 桥接/环境选项，更新 readFunction.md、README 和本地验证记录；跑全量单测、集成测、构建和 Playwright。
