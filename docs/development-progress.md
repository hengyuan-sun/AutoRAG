# 开发执行记录

当前实施方案：[Docling DocumentIR工作台](superpowers/plans/2026-10-23-docling-document-ir-workbench.md)。产品解析路径为Python Docling，保留本地兼容解析器；不要求Go运行时。上游研究材料仅作历史调研，不代表当前部署依赖。

## 当前已完成模块

- DocumentIR 1.5契约、Docling离线解析适配、IR到Chunk来源映射。
- 内容寻址IR产物、workspace范围manifest/分页/详情API和旧解析响应兼容。
- 版本化Consumer Profile、字段选择器校验、来源保留预览和Trial版本固定。
- Vue DocumentIR浏览器、原文定位和Consumer Profile编辑/预览界面。
- 五种切分、黄金集评测、发布与回滚闭环继续通过回归测试。
- OBS/企业来源流、MineU接入、Milvus备用、OCR资产验收及1000页PDF性能验收仍属后续工作。

## 验证记录（2026-10-23）

- 后端：`.venv\\Scripts\\python.exe -m pytest -q`，78 passed、2 skipped；Skip包含需要可选PDF模型运行时/本地资产的用例。
- 静态与依赖：Ruff、`pip check`、`git diff --check`通过。
- 前端：`pnpm test` 5 passed；`pnpm build`通过。
- 浏览器：Playwright使用合成PPTX完成Docling解析、DocumentIR浏览和来源高亮、Consumer Profile创建/预览、切分、黄金评测、发布及回滚，1 passed。
- 真实集成：`RAGLAB_RUN_INTEGRATION=1 .venv/Scripts/python.exe -m pytest tests/test_live.py -q`，1 passed；这不是负载或OCR质量基准。

Go桥接原型此前未完成编译和服务端验收，现已从活动代码、配置和运行文档清理；当前解析实现不依赖它。
