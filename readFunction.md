# AutoRAG 中文实现逻辑说明

本文持续随模块更新。设计依据为docs中的v3方案；已实现功能和未来功能分别记录。

## 一 切分模块

`src/raglab/chunking.py`提供递归、滑动窗口、标题条款、FAQ、表格行组五种真实实现，
每种策略通过API返回名称、说明、推荐长度和策略专属字段标签。切换策略时前端更新推荐参数；
表格策略隐藏并拒绝重叠，避免出现界面允许、实现忽略的配置。
递归中的长度是单块上限：先使用段落/句子分隔符，仍然超长才继续切；固定窗口则每次按窗口长度移动。
每个解析块内使用Unicode码点的左闭右开区间。Chunk同时保存spans和render segments，
因此同样文字出现在不同文档或位置时不会误合并。表格重复表头引用原始表头区间，
不会成为额外黄金证据。超长表格行保留完整内容并警告，不静默截列。

参数校验拒绝非正长度、负重叠及重叠大于等于窗口。递归策略优先段落/句子边界，
退化到字符窗口时保证推进。预设当前以块为单位切分，跨块聚合、父子和语义策略尚未实现。

验证：`tests/test_chunking.py`，覆盖五种策略、Unicode、非法参数、来源覆盖与表头。

## 二 指标模块

`src/raglab/metrics.py`对(文档版本ID,块ID)分组，合并区间后计算交集和并集，
不按词面字符串判断证据。实现Recall、Precision、IoU、实际字符成本精度及冗余，
检索排名按去重文档计算Recall/Hit/MRR/nDCG，RRF使用1/(60+rank)。

ContextAssembler按实际交付的文本截断并重新投影来源区间，换行同样计入预算。
当前只支持精确字符预算；Token预算因未绑定Tokenizer而明确拒绝，避免伪造Token数。
空黄金标签返回null，空命中且有标签返回0。浮点断言采用容差。

验证：`tests/test_metrics.py`，包含不同文档相同位置、重复命中、截断和手工算例。

## 三 持久化与文件

`persistence.py`使用SQLAlchemy。lab_records保存带workspace和kind的版本化资源；
lab_jobs保存任务、lease和fencing token；lab_vectors在PostgreSQL上使用pgvector真实向量类型，
单元测试使用SQLite JSON向量。正式环境不会使用SQLite模拟检索来宣称pgvector验证完成。

BlobStore流式接收、累计SHA256及大小，临时文件完整写入后原子更名，超限/失败清理临时文件。
Blob读路径只接受64位hex，防止目录穿越。外部访问产物必须先由业务层检查资源workspace。

任务通过事务和行锁领取；资源和向量的每次事务写入都会锁定并核对当前job owner、fencing token和租约，
旧Worker即使恢复运行也不能保存评测/Trial或覆盖索引。发布指针使用CAS比较expected_release，
只有符合当前活动版本的写入可成功。测试覆盖跨工作区拒绝、幂等、旧Worker与并发发布语义。

## 四 DocumentIR契约

`src/raglab/document_ir/models.py`提供与解析引擎解耦的DocumentIR 1.5数据模型：文件元信息、引擎身份、章节树、标题/段落/表格/图片/公式、目录、页眉页脚、来源区间和物理定位、证据状态、关系、页记录、provider/config快照、外部产物及分片manifest。每个内容项保留稳定UID；无法从解析器取得的页码、坐标或字段保持缺省，不由模型推导。

模型使用Pydantic v2判别联合检查核心条目类型，并对页码、行列坐标、区间、bbox和有限数值做字段级校验。未知的引擎扩展数据可随模型保留，接入方应放在`extensions`命名空间；业务规则通过`validate_document_ir`集中检查UID唯一性、parent/outline/关系引用、表格单元格边界和来源区间。

调用方先`DocumentIR.model_validate(payload)`，再调用`validate_document_ir(ir)`完成跨项检查；持久化使用`model_dump(mode="json")`。该模块只定义和验证解析结果，不负责将IR转换成Chunk，也不把Docling对象泄漏到API或业务配置。

验证：`tests/test_document_ir_models.py`覆盖1.5核心项类型、JSON往返、位置和证据状态；`tests/test_document_ir_validation.py`覆盖重复UID、悬空关系、越界单元格和非有限坐标。

## DocumentIR到Chunk来源映射

`src/raglab/document_ir/chunk_projection.py`是DocumentIR进入现有切分器的唯一边界。标题、段落和表格生成临时ChunkingBlock；图片/公式继续留在IR，首期不隐式拼入检索文本。每个投影块ID就是稳定IR item UID，保留章节路径、可用页码/bbox、来源位置和字符跨度。表格按行/列序列化为切分文本，同时记录每个单元格在投影字符串中的Unicode码点范围。

`chunk_document`输出的每条来源span都包含document_id、item_uid、block_id和投影文本左闭右开区间，并带上可用位置及相交的cell UID/行列坐标。重叠窗、标题重复和表格表头重复仍指向原IR区间。指标模块只使用document/block/区间字段，额外来源证据不会改变Recall、Precision或IoU。Trial固定parser identity、IR schema版本、解析快照hash和切分参数；解析器或配置变化产生新快照，切分参数扫描复用相同解析结果。

验证：`tests/test_ir_chunk_projection.py`覆盖heading context、表格单元格来源和Unicode精确回链；`tests/test_chunking.py`验证新span保留原解析块身份；`tests/test_metrics.py`保证新增来源字段不改变既有证据指标。

## 五 解析身份

`src/raglab/document_ir/docling_adapter.py`使用锁定的Docling 2.142.0 Python SDK，将路径文件转为DocumentIR 1.5。
IR投影接入后新实验默认Docling；平台同时保留local-baseline@2用于读取旧快照和兼容解析。Adapter身份包括SDK版本、
适配器版本及规范化pipeline配置摘要，文件hash和该身份共同决定解析缓存。Docling导出的标题、段落、
表格单元格、图片/公式占位、章节路径、能取得的页坐标和warnings进入统一模型；缺失页码/坐标继续为空。

Docling读取路径文件。`Lab.parsed`从BlobStore以64KiB块写到临时文件，解析完成或失败后删除临时文件，
不会把500MiB上传额外读入内存。TXT通过临时Markdown文件交给Docling，仍按磁盘流式复制。
PDF运行强制离线：必须配置本地模型资产目录，并安装可选`docling-pdf`依赖；未满足时返回明确原因，
不会退回旧解析器或联网下载。OCR默认关闭，需要时安装`docling-ocr`并显式配置。

旧Local解析器仍输出兼容blocks；DocumentIR在Task 3投影层转换为带UID和原文来源的ChunkingBlock，
不能把Docling原生对象直接当作切分块。MineU/MinerU后续也通过解析适配器注册。

## 六 开发验证状态

后端默认套件45项通过、1项真实依赖用例默认跳过；启用集成环境后，真实Ollama与PostgreSQL/pgvector链路1项通过。
前端Vitest 3项通过，Playwright完整闭环1项通过，Vue类型检查及Vite生产构建通过，Ruff静态检查通过。
评审回归覆盖失效租约写入、旧模型身份、文档TopK以及黄金集嵌套字段校验。

## 七 领域服务和三个闭环

`service.py`的Lab是API与Worker共享的领域入口。资源操作均接收workspace，
外部HTTP单机身份固定为local，客户端不能通过自报workspace越权。

摄入先检查知识库，再流式存储。业务身份由知识库/来源/外部文档ID区分，修订作为独立键；
相同修订相同hash返回原资源，不同hash返回409。未显式指定修订时，人工上传采用内容hash。
当前文档清单按每个逻辑身份最新接收的修订生成，企业来源事件排序策略尚待连接器实现。

实验创建不可变配置与模型绑定，逐组执行。解析缓存包含文档ID、源hash、解析器身份，
修改窗口可复用同一解析快照；Embedding缓存包含实际输入、角色与完整模型绑定。
每个Trial固定文档清单、解析快照hash、切分参数、模型digest及Chunk产物hash。
数据写入候选index_version；持久化成功后才标READY。不同方案失败独立记录，全部失败则任务失败。
重试可跳过READY Trial并复用已完成的模型调用；这不是通用DAG阶段检查点系统。

检索检查Trial归属后，按该Trial固定模型生成查询向量。pgvector执行带workspace和index_id过滤的余弦查询。
全文基线以中文单字/二元词组和英文词条执行BM25，RRF按排名融合。
块级候选先全量按文档最高分聚合，再生成独立文档TopK用于Recall/MRR/nDCG；
块级TopK单独装配字符预算上下文。Trace保存两路候选、实际上下文及来源。

`golden.py`定义API与服务共用的GoldenItem/EvidenceSpan契约，JSON/CSV在落库前检查嵌套字段类型。
黄金集导入检查问题ID、文档版本、知识库归属和区间格式。评测前核对每个span的块和范围，
不能精确对齐时将该题标记错误；有效题执行失败计零，错误率独立记录。
无标签指标返回null。总分采用题目宏平均；P95使用nearest-rank。
完整逐题Trace持久化在evaluation资源中，前端可以展开和导出。

发布时重新冻结知识库当前全部文档清单，用原Trial的切分/解析/模型配置构建完整索引，
再对候选执行黄金集，文档Recall达到指定门槛且错误率为0才得到READY Release。
未通过Gate的版本仍保存REJECTED及指标。首期Gate不等价于v3全部多指标/相对基线能力。
激活/回滚通过expected_release_id执行CAS，模型digest不再可用则拒绝；
单条查询开始时固定Release，原数据和模型配置不会因默认配置改变而混用。

## 八 模型适配

`models.py`在/api/tags中按绑定内的模型名定位Ollama模型并固定digest，/api/embed使用truncate=false，
对文档与查询使用不同的角色缓存，查询加入固定检索指令。
每批新Embedding前核对当前digest，数量、维度、有限数均校验。
旧缓存只用于相同模型身份及实际输入，不跨工作区共享。
Reranker尚未启用；模型已安装不等于评分协议已验证。修改默认模型不会使既有Release失效；
只有原绑定模型被卸载或其digest改变时才拒绝激活或继续检索。

## 九 API与后台任务

`api.py`以FastAPI提供知识库、文件流、实验、评测、发布和检索接口，
请求采用Pydantic限制长度、枚举与参数组数。401表示无令牌，403只读拒绝，
404资源不存在或无权限，409幂等/发布冲突，422参数问题，503外部依赖不可用。
管理员和可选只读令牌在服务端映射身份，不依赖前端控制权限。

单机服务内嵌一个Worker线程；也可用`python -m raglab.worker`运行独立Worker。
job领取后启动15秒心跳，60秒租约，fencing token保证旧Worker不能提交最终任务状态。
崩溃后过期任务可重新领取；外部向量写入使用稳定Chunk键和候选索引隔离。
尚未提供取消任务、后台产物GC和生产级阶段分布式协调，不能将其视为完整调度平台。

raw入口逐个读取请求分片，累计hash及大小后才调用摄入，断流不创建成功资源。
multipart文件使用上传临时流，单文件上限默认500 MiB；摄入不会为推导默认revision重复写Blob，超限返回413。
JSON/CSV黄金集导入上限5MB。
Blob引用必须经业务资源授权后访问，当前没有公开原始Blob下载端点。

## 十 前端实现

`frontend/src/App.vue`按文件试验、黄金评测、版本发布、历史诊断四个工作区组织。
连接令牌仅保存在sessionStorage，不打包进静态资源；请求通过api.ts统一加鉴权及展示结构化错误。
长任务返回job_id后轮询持久状态，而非依赖单个HTTP请求一直等待。
选择Trial加载分页Chunk预览，切换知识库会清空旧选择；异步响应核对当前选择，防止展示过期结果。
完成通知不被数据加载watcher重置，此问题由真实浏览器测试发现并修复。

评测列表展示文档与证据指标，缺少证据时N/A；逐题页面展开实际上下文与Trace。
发布页面先完整构建，再由用户点击激活，历史READY版本可显式回滚。
OBS、Rerank、Token预算在诊断页面标记尚未启用，不能把预留项显示为已运行。

## 十一 RAGFlow定制文件

`patches/ragflow-parser-bridge/main.go`在冻结Go模块内复用官方Parser，
实现带独立令牌的/internal/v1/parse。DOCX要求JSON结构；PDF首期明确plain_text；
Markdown禁用远程图片下载。TableData映射为行组并保留原始结构，未知页码返回null。
脚本`scripts/prepare_ragflow.py`检查SHA和干净工作区后应用可复现构建目标改动。
当前工作站无Go工具链。Docker Hub Go镜像下载遇到鉴权连接EOF，官方Windows工具链直连下载因速度过慢超时；且上游构建还需要Linux及CGO原生库。因此桥接源码尚未完成真实编译/端到端验证，
API契约测试使用隔离HTTP传输检查字段与拒绝错误revision，不将其称为真实上游测试。

## 十二 已知后续模块

精确Tokenizer、父子/语义算法、公开基准下载适配、完整GatePolicy、OBS/来源ACL、
Milvus备用路径、产物GC、备份恢复脚本及RAGFlow运行验证继续按v3里程碑推进。
当前交付是三个本地研发闭环首个可运行版本，不等于v3全范围或生产验收完成。
