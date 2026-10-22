# AutoRAG 中文实现逻辑说明

本文持续随模块更新。设计依据为docs中的v3方案；已实现功能和未来功能分别记录。

## 一 切分模块

`src/raglab/chunking.py`提供递归、滑动窗口、标题条款、FAQ、表格行组五种真实实现。
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

任务通过事务和行锁领取；旧租约不能提交。发布指针使用CAS比较expected_release，
只有符合当前活动版本的写入可成功。测试覆盖跨工作区拒绝、幂等、旧Worker与并发发布语义。

## 四 解析身份

`parsing.py`包含显式local-baseline@1，用python-docx/pypdf解析DOCX/文本PDF及TXT/MD。
DOCX保留段落顺序和表格行，Markdown保留标题路径；没有可靠页码时返回null。
扫描件无文本时失败并说明需要OCR。该解析器不冒充RAGFlow。

RAGFlow适配调用配置的`/internal/v1/parse`内部桥接，校验revision、parser身份及blocks。
未配置桥接时明确失败，不偷偷改用本地解析。上游Go源码构建及端到端验证另行记录。

## 五 开发验证状态

模块M1/M2已通过19项本地单元测试（初次RED共19项，随后实现转GREEN）。
后续实验、API、前端及外部服务结果将追加到本文，不把计划测试算作已执行。
