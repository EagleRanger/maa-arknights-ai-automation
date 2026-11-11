---
name: arknights-automation
description: 通过现有脚本和MAA执行明日方舟日常、剿灭、活动推图刷取、基建、保全派驻、肉鸽与生息领奖加点，以及已接入的培养和凭证功能。用于Windows本机首次配置、单项调用、日常组合、页面异常接回和真实结果核验；不重新编写控制器，不假装待接入功能已经可用。
---

# 明日方舟自动化

这是带执行源码的脚本程序；AI对话是自然语言入口，不需要额外图形前端。AI理解用户任务、填本机参数、调用现成接口并看图处理异常；脚本负责固定动作、范围隔离、记录和效果核验。

**按程序使用，不重新做源码审计。** 正常接入先运行下面的只读目标菜单和参数说明，再按[本机接入](references/receiver-integration.md)补配置，最后调用用户目标。只读入门咨询也按这些公开接口答复；不需要沿历史版本链逐个读函数来证明它们存在。只有具体命令实际报错或用户要求研发时，才按报错定位相应实现。参数模板里没有填好的账号数据不能猜，但这不妨碍解释真实可用命令。

## 先知道能做什么

在完整包的 `runtime/` 工作目录，用已配置的Python运行：

```powershell
python ark.py list
python ark.py describe <任务名>
python ark.py template <任务名>
```

这是按人类业务目标组织的公共目录，列明目标参数、命令与当前范围。截图、OCR、环境准备、返回、分步提交和核验是内部配套，不是用户任务。列目录、看说明、输出模板都不会启动游戏；不要从历史脚本中猜入口，也不让用户或AI正常调用时手工拼内部步骤。

| 用户要做的事 | 公共任务名 |
| --- | --- |
| 完成默认日常，或选模块、改顺序组合日常 | `daily` |
| 完成本周剿灭并领奖 | `annihilation` |
| 推进活动已开放普通/EX/突袭和附加内容，最后领奖 | `event` |
| 刷活动材料或用户指定资源关 | `farm` |
| 领取当期签到、许愿墙和活动任务奖励 | `activity-rewards` |
| 管理基建、生产轮班，或指定活动室信赖/无人机目标 | `base` |
| 完成保全及周期奖励（内部自动编队和战斗） | `sss` |
| 肉鸽刷经验并在结算后领奖加点，或只处理已有奖励/加点 | `roguelike`，`mode`区分目标 |
| 生息刷分或领取已有繁荣奖励 | `reclamation` |
| 新版卫戍协议一轮刷取积分并核验 | `stronghold` |
| 完成配置中指定干员的技能专精 | `training`（Beta） |
| 处理指定干员的模组任务、解锁和目标等级 | `module`（Beta） |
| 凭证商店观察、整套黄票规划、具名红票兑换 | `vouchers`（按当前接入范围） |
| 推进指定主线目标 | `mainline` |

活动室整套升级、绿/黄票完整自动购买、卫戍自动清店等尚未形成完整公共执行链，不冒称能自动完成。具名模组升级当前只适配怒潮凛冬HAM-X，不给其它干员硬套。教学关和陌生页面的AI看图操作、截图/状态查询、报价核验等属于目标内部的配套能力；研发扩展和内部步骤只在需要时用`ark.py debug list`查，不混在正常目标菜单里。

## 第一次安装

先读[本机接入](references/receiver-integration.md)，按真实MAA、MuMu、游戏渠道、OCR和基建配置填写 `runtime/config/receiver_profile.json`。用户自行登录账号，不需要密码或验证码。再运行：

```powershell
python ark.py init
python ark.py check
python ark.py check --task daily --probe
```

`init`生成本机运行绑定和通用任务规则，不复制作者Loop、组件历史或账号完成状态；不覆盖已有工程/用户修改。`check`不是游戏操作；`--probe`核MuMu身份、OCR及便携MAA，包含一个临时写入探针，不开始业务。缺配置按错误中指出的字段/文件补齐，不另写适配器。已有工程继续原入口，升级由用户自己的AI对照本地修改合并，不强制重新安装。

## 按业务目标调用

用户明确任务就是相应正常准备、执行与核验的授权，不为同范围普通点击反复确认；账号、药石、购买及截止边界不扩大。本版公共入口只用现有理智，不用源石或药剂。

```powershell
python ark.py run daily
# inputs.json例：{"theme":"Sami","mode":"rewards"}。这里只领奖，不加点、不探索。
python ark.py run roguelike --inputs inputs.json
# 独立保全模块：内部完成编队、战斗、结算及领奖，不附带整日日常。
python ark.py run sss
```

调用返回本次目录，准备环境、安排内部步骤和保存过程由脚本负责。普通单项目标返回后保活，便于同一AI处理异常或继续其它已授权目标，不自动关游戏。正常执行不要求调用者手工组合截图、编队确认或领奖核验；只有异常接回/研发才查看内部步骤。**“已提交”不是完成；原MAA仍在运行时不要抢控。** 配套`status/action`和独立卫戍/肉鸽控制方法见[入口与续接](references/entrypoints-v125.md)。

日常就像MAA勾选任务：默认`run daily`沿原组合不变；用户特调时用`run daily --inputs daily.json`，例如`{"modules":["base","recruit","mall","award"]}`。只执行所选模块并保留数组顺序，不补进战斗或其它未选任务。每项也可写`{"task":"base","inputs":{"action":"routine"},"enabled":true}`；可选模块和参数边界由`describe daily`列出，AI负责配置，不要求用户拼内部步骤。自定义组合返回原模块会话，做完用`finish`补收新待办再退出；不会回退整日full。

可配置不等于所有原生选项都已接入：当前卫戍自定义阵容/难度会明确拒绝，不能丢掉参数后跑默认；新剿灭首通找作业链尚未接到公共目标；主线公共核验当前适配1—9章点名普通关，其它难度不能拿默认层次代替。具体限制按`describe`和入口说明，不从“MAA有此能力”推定本包已接通。

## 脚本不会时AI接着做

先确认原控制器和MAA队列。队列仍运行时不点击、不抢鼠标。队列空闲后看新图，处理已授权的关闭、返回、确认或当前未完成动作；识字差异或陌生弹窗不等于整日失败。使用原会话 `action` 的 `observe/tap/back/swipe/home/prepare`，参数格式见入口说明。点按/拖动必须绑定刚看过的新图序号。

动作后重新看图，再用 `continue <业务目标> --output <原目录>` 继续未完目标。原日常若正在导航等待，沿已附 `tools/ark_navigation_reply_v1.py` 提交真实首页证明并确认原脚本继续；证明工具不代替点击，也不证明领奖。效果未知先对账，不为修报告重打；某可选活动无法处理时，只暂停其依赖，继续独立任务。确需改代码才转项目，不要求每次普通恢复先找作者。

## 真正完成与退出

战斗看实际结算/通关标记；奖励看已领取或数量变化；培养看实际等级，不能把“训练开始”算专三完成。账号事实按[账号记录](references/account-progress.md)保存，未知不填零，手动完成不记为自动成果。

普通模块会话中，本次用户目标做完、没有后续目标时，使用配套`ark.py finish --output <本次目录>`；脚本自行补收新增基建、招募和任务待办，再核验并退出，不要求AI手工拼收尾、不重跑五链或战斗。完整daily沿原日常自动收尾；持续肉鸽和卫戍沿各自原宿主结束口，不把普通会话命令交给另一个控制器，见[入口与续接](references/entrypoints-v125.md)。异常不默认关闭健康环境；明确停止/截止按原任务收口。最终用人话说已成、未成、剩余资源和环境状态，不用文件存在、进程存在、回调完成或测试通过替代游戏效果。

特殊规则按需读：[活动与逐关](references/workflows.md)、[保全桥接](references/sss-formation-bridge.md)、[肉鸽/生息](references/progress-modules.md)、[卫戍](references/stronghold-protocol.md)、[培养/凭证](references/operator-and-voucher-interfaces.md)、[故障接回](references/continuity-and-signin.md)、[教学](references/tutorial-ai.md)。不要首次恢复就加载全部参考或任何作者私有Loop。
