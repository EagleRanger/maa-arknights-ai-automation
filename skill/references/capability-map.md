# 我想做什么？
在 `runtime` 目录运行 `python ark.py list`。下表是可直接选择的目标；`python ark.py describe 目标名` 给出参数和限制，`plan` 只预览，`run` 才执行。

| 需求 | 目标 | 使用范围 |
| --- | --- | --- |
| 默认或自选日常 | `daily` | 不带参数走默认链；自选只执行启用项，见[组合示例](entrypoints-v125.md)。 |
| 本周剿灭 | `annihilation` | 用已有代理补周奖励；新图未达到 400 不冒充可代理。 |
| 活动推进、刷材料、只领奖 | `event` / `farm` / `activity-rewards` | 三个独立目标。进图、按库存刷关和领取奖励不是同一件事。 |
| 基建 | `base` | 用本账号排班；也能按选项处理无人机或活动室信赖。 |
| 保全派驻 | `sss` | [自动编队、战斗与周期奖励](sss-formation-bridge.md)连起来执行。 |
| 肉鸽 / 生息演算 | `roguelike` / `reclamation` | 分清刷分、已有奖励和肉鸽加点，见[分主题参数](roguelike-rewards.md)。 |
| 卫戍积分 / 策略角标 | `stronghold` / `stronghold-badges` | [积分](stronghold-protocol.md)与[角标](hard-trial-review.md)分开；不接收未实现的自选阵容或难度。 |
| 悖论模拟 | `paradox` | [自动找一名未通过者](paradox-simulation.md)，不附带培养。 |
| 技能专精 / 干员模组 | `training` / `module` | [按账号选择](operator-and-voucher-interfaces.md)。点名只做该人；模组默认一阶。 |
| 凭证交易所 | `vouchers` | 查看、黄票预算或具名红票兑换；不把预算当购买。 |
| 主线 | `mainline` | 指定普通关，当前公开入口适配第 1 至 9 章；不自动扫旧章节。 |

首次设置见[接入](receiver-integration.md)。遇到中断看[接续](continuation-and-closeout.md)；各玩法的已知限制见[可选功能](beta-features-20261103.md)。

需要排错时按问题查：[识别偏差](recognition-and-service-gates.md) · [完成凭据](evidence-validation.md) · [日报数字](result-ledger-and-reconciliation.md) · [配置与资源范围](runtime-contract.md)。
