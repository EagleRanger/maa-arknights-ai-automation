# 永久进度模块（测试）

在接收方已准备、MAA空闲、具有唯一控制权的会话内调用
`permanent_progress_modules_v1.run(app, theme, action, output)`。
theme 为 Phantom、Mizuki、Sami、Sarkaz、JieGarden、BlackFlow 或 Reclamation；
action 为 inspect、rewards、growth，Reclamation 不接受 growth。

- `ark_modules.progress_operations_v1.ProgressRuntimePort` 复用原 RuntimeSession，
  按独立 operation 调用；动态依赖 `ark_modules/domains/progress.py` 已随包。
- `roguelike_progress_adapter_v1.adapter` 将接收方原 explore/settle 回调与新模块组合：
  刷分 → 结算 → 领奖 → 有点数时加点。单独 rewards/growth 不调用刷分。
- 完成态、零点数、无待领与兑换售罄分别判断；未识别数值不能当零。
  导航兼容字形/简繁/全半角/装饰符，失败先ROI放大、新帧重读；
  数值和实际领取/兑换效果仍需直接证据。
- 不自动开局、弃档或关闭宿主；未知页返回同owner的AI接手。
  新主题正向加点与生息有余额兑换仍为AI辅助，不把测试说明当作已经稳定。

源码已完成一轮六主题领奖/加点状态检查加生息领奖检查的13项真实调用，
不等于13轮稳定性或每项均发生新领取。该扩展未替换旧长期探索入口，
也没有强塞进每日默认链。按需组合并保留接收方资源策略。
