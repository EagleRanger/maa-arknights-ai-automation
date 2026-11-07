# 接收方 AI：功能总览与调用地图

先从用户要做的事情找到已有实现，再绑定本机环境和账号配置；不要只看 MAA 主界面有哪些按钮。MAA 是具体执行能力的集合，本 Skill 负责外层目标、顺序、桥接、结果核验和异常接回。

下面的路径相对完整包的 `skill/runtime/`。它们是源码定位点，不是让接收方裸调用所有旧脚本的启动命令：实际执行沿本机已装配的宿主、当前发布组合和单项入口。仅有 Skill 说明目录、没有 `runtime/`，不等于安装了执行代码。

## 能做什么、接哪里

| 功能 | 已有代码／接口 | 接收方需要做什么、当前范围 |
| --- | --- | --- |
| 每日日常 | 当前发布组合（本次核验 v1.2.3 为 `run_daily_v167.full()`）；`ark_modules/domains/daily.py` | 绑定本机启动器与日常选择。沿既有链完成启动、招募、信用商店、基建、任务奖励和收尾，不另造每日流程。以后升级使用新包的实际入口，不永久锁定这个历史文件名。 |
| 周剿灭 | 引擎 `mode_annihilation()`、`annihilation_rotation_v4.py`、`annihilation_postclear_v2.py` | 核当周报酬、当前轮换图和首通状态；未通关时匹配作业，已满足条件按用户策略用代理卡；400 杀与后续奖励分别核验。 |
| 活动普通／突袭／EX、复刻与主线 | 引擎 `mode_event_today()`／`mode_mainline()`；`event_layout_profiles_v1.py`、`event_copilot_feedback_v1.py` | 用真实开放时间、关卡和通关标记决定未完项。AI 选适用现成作业，MAA 执行，原循环核结果、按预算重试或换作业。新玩法需要对应适配，不能凭旧活动编号直接跳转。 |
| 教学关代理逻辑（测试） | `tutorial_ai_handoff_v2.py`、`tools/tutorial_session_v2.py`、`tutorial_session_result_v1.py`；[教学关说明](tutorial-ai.md) | 无适用作业时，先由 AI 依当前提示、部署格与朝向通过原后台通道操作；实际尝试仍不能完成才提示人工。已有单关实测，不宣称所有教学都能自动通过。 |
| 理智与批量代理 | `daily_batch_proxy_v1.py`、`event_farm_detail_handoff_v1.py`；引擎资源／搓玉材料兜底入口 | 根据实际理智、费用、代理条件和倍率控件决定批量，不固定每次只打一次。材料选择按当前库存和目标；周剿灭、活动及无活动兜底沿用户已定优先级。 |
| 登录配给、限时签到、许愿墙 | `daily_login_supply_v4.py`、`event_daily_reward_chain_v1.py`、`event_signin_generic_v3.py`、`event_wish_wall_v1.py` | 识别当期弹窗和首页标签、核活动有效期；支持已覆盖布局的领奖和返回。活动结束即跳过，陌生布局交执行 AI，不把签到做成全年硬前置。 |
| 活动任务与逐日解锁附加内容 | `event_tl_task_rewards_v1.py`、`event_press_committee_v2.py`、`press_committee_native_fallback_v1.py` | 刷取后再核新奖励。本期报纸按分页、解锁状态和完成标记处理；MAA 停在部分组版时可用[原地看图接手](workflows.md#committee-live-visual-takeover)，新接手候选已单项实测，仍要核实际运行版本是否接入。新增活动按实际界面适配。 |
| 基建收菜、轮班、生产贸易与无人机 | `ark_modules/domains/base.py`、`ark_modules/base_forecast.py`、`daily_base_333_drones_v1.py`、`daily_recycle_infrast_v1.py` | 配置本账号实际设施、库存、搓玉／赤金等目标，兼顾产出和消耗；无人机与升级预留按用户目标。333 是已有策略，不是强制每个用户改建。 |
| 活动室升级、材料与信赖培养 | `run_activity_room_service_v1.py`、`activity_room_plan_v2.py`、`activity_room_upgrade_v1.py`、`activity_room_trust_select_v1.py` | 可选单项，绑定本账号设施、材料和升级／信赖目标；升级完成后再把无人机交回生产策略。不给新用户默认下达升级或材料消费任务。 |
| 保全自动编队、作业战斗和周期领奖 | 引擎 `mode_security()`／`run_sss_copilot()`；`sss_cycle_service_v1.py`、`sss_reward_pages_v3.py` | 关键：先接[编队桥接](sss-formation-bridge.md)，不是直接调用原生 SSSCopilot。新区域可由 AI 按作业生成账号配置；委托卡、区域记录和周期封顶分别处理。 |
| 肉鸽探索、领奖、永久加点 | `run_sami_progress_v9.py`、`roguelike_mode_v1.py`；[共用模式](roguelike-mode-and-extension.md) | 原生探索、整轮结算后领奖／加点，已验证满级由账号记忆跳过。银凇为当前主要接入；其它主题、月度／调查等模式要看实际适配，不把协议支持当全部 UI 已实测。 |
| 肉鸽反复失败观察与优化接口 | `roguelike_battle_watch_v1.py` 的 `boundary`、`proposal_hook` | 记录重点关、部署与少量截图，交 AI 分析；默认只产建议，不在战斗中改作业或自动换阵容，不增加第二个控制器。 |
| 生息演算 | 引擎 `mode_reclamation()` 与所装 MAA 的对应能力 | 保留独立任务入口。MAA 将原队列功能迁到小工具时，核实际消费者再用；旧入口存在不代表更新后已经兼容。 |
| 技能专精培养（Beta） | `operator_training_v2.py`、`operator_training_infrast_v1.py`、`tools/run_operator_training_v1.py` | 用户指定干员、技能与顺序；先复用基建训练室观察，保留正在训练的目标，实际等级达到后才推进下一项。见[培养接口](operator-and-voucher-interfaces.md)。 |
| 模组任务、解锁与升级（Beta） | `operator_module_missions_v2.py`、`tools/run_module_missions_v2.py`、`tools/module_upgrade_trial.py` | 先查实际模组进度，再补任务与指定等级；当前具名样例为怒潮凛冬 HAM-X，不能给其它分支直接套。未授权解锁／升级只观察或做指定任务。 |
| 绿票、黄票、红票（Beta） | `voucher_exchange_plan_v1.py`、`maa_utility_custom_v1.py`；[凭证接口](operator-and-voucher-interfaces.md) | 黄票有整套预算规划，绿黄票有原生兑换接缝但购买闭环仍待实测；红票已接一件芯片助剂试用。信物换票、干员兑换未由当前适配验证，不宣传为已自动完成。 |
| 单项插入、补做与最后补领 | `ark_modules`、`run_daily_remaining_v7.py`、`run_daily_final_tail_v2.py`、`ark_modules/exit_tail.py` | 单项不带出整日流程；只补未完成的域。退出前按任务范围核新产生的基建／招募／任务奖励，不能重放已完成战斗或轮班。 |
| 异常恢复、实图判断与账号记忆 | `ark_host/cooperation_v1.py`、`daily_ai_navigation_v1.py`、`ocr_tolerance_v1.py`；[账号事实](account-progress.md) | 脚本有界恢复，仍不明确交执行 AI；接收方绑定自己的消息／回复通道。记录实际效果并影响下次决策，不拿回调成功代替游戏完成。 |
| 定时、结果报告与更新提示 | 本机宿主定时入口、当前日常启动绑定；[更新与本地合并](release-notices-and-local-merge.md) | 按用户设置使用宿主定时能力，不再另设轮询任务。报告已成／未成和资源实测；发现新版本只提示，由用户自己的 AI 合并本地修改，不自动覆盖。 |

## 对接时不要漏的三件事

1. **文件、入口、实效分开核。** 文件在包里，不代表接收方的启动器加载了它；启动器加载了，也不代表新 MAA／新页面已经实测。记录实际入口、模块路径、MAA 版本和对应结果即可，不另建繁复审批。
2. **缺配置与缺能力分开。** 例如保全工具人名单由接收方 AI 按作业和账号补齐，之后复用脚本选人；不能因为没有某区域预置名单就宣布保全必须全部手选。页面／协议变更才修相应适配。
3. **主链、可选模块、账号事实分开。** 既有每日默认链不重排；肉鸽、培养、模组、兑换等按用户目标启用；作者账号的进度、阵容、库存及资源偏好不是接收方默认值。

## 升级后怎么查是否接上

- 核完整包和实际加载的 `runtime`，不要只换 `SKILL.md` 或只看到版本号就认为代码已生效。
- 复用当前包的接收方入口说明和 `SOURCE_MANIFEST.json`；同版重新打包的文件也可能不同，合并时检查具体改动，保留自己的配置。
- MAA 更新优先核变动的功能边界：设置指引／任务配置、编队、作业开始、返回领奖与继续下一项。日常中途不为升级打断已开始的业务。
- 当前用户任务中首次用到改变的分支时核实效果；纯文档更新不为凑测试重开游戏、消耗资源。待验证功能按功能标 Beta，不把整个包写成保证全自动或全部不稳定。

单项与组合调用见[永久进度模块](progress-modules.md)。
