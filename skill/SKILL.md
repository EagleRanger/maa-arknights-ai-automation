---
name: arknights-automation
description: 在 Windows 上用 MAA 和安卓模拟器运行明日方舟日常，或单独处理关卡、基建、领奖、干员培养和限时玩法。
---

# 明日方舟自动化

在 `runtime` 目录用接收方配置的 Python 运行 `ark.py`。以玩家这次要求为准。只点名一个目标，就不带出整个队列或整日日常。不要把活动材料改成芯片，不用计划以外的药剂、源石或兑换预算。

- **首次使用**：按[安装与配置](references/receiver-integration.md)绑定本机模拟器、游戏账号和 MAA；`python ark.py check --task daily --probe` 只检查，不开游戏。只用单项时，把 daily 换成该目标。
- **选择任务**：`python ark.py list` 看玩家目标，`describe 目标` 看选项。`plan 目标` 预览要执行的对象；确认与请求一致后，用同样参数运行 `run 目标`。只做指定玩法，不把“没找到作业”当作开新任务的理由。自由组合日常见[功能表](references/capability-map.md)。
- **干员模组**：用 `module`。不带参数只列清单和推荐；`--operator 干员名` 只处理这一人，默认一阶，不加入长期队列。多个分支不能唯一确定时再指定分支和实际模组名。明确说“加入队列”才用 `--action add`；“做队列下一项”用 `--action next`。详见[干员培养与兑换](references/operator-and-voucher-interfaces.md)。
- **中断或重复请求**：对原模块会话运行 `python ark.py resume --output 原输出目录 --check-only`。脚本列出已做、未做和下一步；只有返回 `continue_remaining` 才去掉 `--check-only` 续跑。效果不明时先看当前画面和结算，不重提、不另开控制器。终态或过期会话不重播。正式每日以当天日报和运行记录为准，昨天的专项不是今天的待办。
- **结束**：看业务证据，不把队列结束当作游戏成功。说明目标是否完成、有什么未完成、程序是否已关。需要结束已打开的模块会话时，用 `finish --output 原输出目录` 补收新待办并退出。用户要求留场则不关闭。

按需阅读：[活动与签到](references/continuity-and-signin.md) · [悖论模拟](references/paradox-simulation.md) · [肉鸽领奖与加点](references/roguelike-rewards.md) · [卫戍角标与高难复盘（待测试）](references/hard-trial-review.md) · [OCR 环境](references/local-ocr-setup.md)。
