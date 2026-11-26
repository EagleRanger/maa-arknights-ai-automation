# MAA更新后的衔接

检测到MAA或相关资源更新后核一次，不在每轮日常重复全审。

1. 看实际版本和[该版本公告](https://github.com/MaaAssistantArknights/MaaAssistantArknights/releases)，对照[功能地图](capability-map.md)，只查变化涉及的模型、接口、配置、回调和页面。
2. 有必要的优化修到真实调用点，再同步Skill和配置。已验本地模板、战后复查、失败换作业和异常接回继续保留；不为复用截图重构稳定链。
3. 用原错误图／回调回归；点击或导航变化在下一正常任务验效果。记录变化和未接入项，不重放已完成游戏，也不新增审批／监控任务。

更新在日常中途出现时先延后，完整日常优先。用户本地修改按原[合并方式](release-notices-and-local-merge.md)保留。

## 本次核对：MAA 6.22.0，2026-11-09

[官方说明](https://github.com/MaaAssistantArknights/MaaAssistantArknights/releases/tag/v6.22.0)：桌面中英文／繁体／日服改用PP-OCRv6，韩文为v5；ONNX Runtime默认，WebGPU实验。另有作战日报、卫戍三期适配和设置页调整。以后按新版本重核，不把这条永久当最新版。

- MAA内置OCR与我们独立的v6-small同代但不是同一配置。MAA升级不替Python装依赖；配套要求见[本地OCR](local-ocr-setup.md)。
- 作战日报可用于对账，不替代我们整轮／分段理智、末尾实测余额和新增待办的核验。
- 干员培养按[实际接口](operator-and-voucher-interfaces.md)接入，不把原生支持当公开包已全接通。
- 已有同队列结果就复用；内部图像未必落盘。本地截图／OCR不耗模型Token，稳定时无需替换。识别故障按[结果核验](evidence-validation.md)定位。
