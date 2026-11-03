# 接收方 AI：使用已有执行代码，按本机环境对接

本 Skill 同时提供方法说明和 `runtime/` 中的自研执行源码。它不是一键安装器：接收方 AI 应依据自己的宿主工具、电脑环境和用户目标完成对接。不要从说明重写已有的每日、主线、肉鸽领奖加点和异常续跑逻辑。

## 接收流程

1. 识别本机已有的 MAA、MuMu、Python 和 ADB。缺少的第三方软件、库、模型由接收方 AI 从可信上游获取，本包不重复分发。通用软件沿用正常安装方式，不复制作者电脑目录；但 OCR 模型有固定文件指纹，必须按 [OCR 来源、安装与自检](local-ocr-setup.md) 的指定分发版本取得，不能只按模型名称搜索替代文件。
2. 使用当前宿主能够执行的 Python，按实际缺失情况补齐依赖。已知业务代码涉及 Pillow、opencv-python、numpy、psutil、uiautomation、rapidocr-onnxruntime；独立 OCR worker 使用 `rapidocr==3.10.0`、`onnxruntime==1.31.0` 和指定 ONNX 模型。`PP-OCRv6` 是模型代数，不是 RapidOCR 运行库版本；新旧两个 OCR 接口也不是同一环境。先完成专用 OCR 配置及自检，无需预先完成所有软件版本的兼容矩阵。
3. 让用户自行安装游戏并登录自己的账号。AI 不需要接收密码、验证码或作者的登录数据，也不增加额外身份认证。安装后只检查执行所需的路径、模块、模拟器连接和截图尺寸；不为证明安装而强制打一局或消耗游戏资源。
4. 从接收方当前用户目标建立本机配置和本次任务。首次运行保留空的账号进度、完成缓存和运行记录；不能把作者已通关、已领奖、过期任务或已停止的队列当作接收方事实。
5. 选择下面的已有业务入口，对接本机工具后按用户原任务运行。遇到环境差异只修对应接口；真实效果仍由原游戏画面、队列日志和结果记录核对。

## 现成代码从哪里调用

| 能力 | 现有实现与接缝 |
| --- | --- |
| 每日完整业务组合 | `run_daily_v146.full()`，它复用前序已实现模块；不能只取 V146 一个文件。 |
| 11月3日可选新组合 | `run_daily_v153.full()`：包含活动新内容、训练观察与刷后领奖接缝。接收方按自己的任务选择，默认仍保留V146链；Beta范围见具体模块说明。 |
| 每日的外层任务绑定 | `daily_dispatch_v1.selected_scope(selected, checked)`。用当前发布文件清单、接收方当前任务和目标核验生成绑定；旧 `preflight()` 依赖作者生产登记，不直接照搬。 |
| 主线推进与通用引擎 | `arknights_daily_runtime_v12.py` 的 `mode_mainline()` 等函数；共用环境、识别、独占和清理从 `ark_host` 装配。 |
| 独立模块组合 | `ark_modules.assembly`、`ark_modules.operations`、`ark_modules.runtime_session`；面向已经准备好的 runtime，不默认升级为完整每日任务。 |
| 银凇肉鸽监督、领奖、加点、异常协作 | `run_sami_progress_v3.main()` 复用 V2、V1 与 `run_sami_until_deadline`。V1 的 `admit()` 消费新的本次任务包，外层安装协作与监督逻辑。 |
| 其他主题和功能 | 由 `runtime/` 内既有域模块和引擎实现，参见对应功能文档；当前银凇接法不等于所有主题均经新机器实跑。 |

`runtime/SOURCE_MANIFEST.json` 记录发布源码的路径与 SHA-256。首次对接核对包内容，修改后为接收方自己的版本记录新指纹。新版本身份不表示已经完成游戏实测。

可选培养/兑换模块先读 [首次配置](first-run-features.md)、[干员与凭证接口](operator-and-voucher-interfaces.md) 和 [本次Beta边界](beta-features-20261103.md)。账号事实使用包内 `account_progress_v1`，新账号以未知开始；私有plan未配置时跳过对应可选项，不拦原有日常。报纸布局需在接收方当前真实画面由AI验证/采集；本包不附作者已学布局和已完成缓存。

### 本次增量的实际入口

| 功能 | 代码与外部资源 | 接收方配置 |
| --- | --- | --- |
| 活动刷后领奖 | `event_tl_task_rewards_v1`，由V153安装到原刷后接缝；复用既有截图/OCR和单控制者 | 本期活动身份、允许领奖的当前任务；不复用作者已领状态 |
| 报纸逐页开放/AI布局 | `event_press_committee_v2`、`press_committee_pages_v2`；接收方官方MAA中的 `resource/template/MiniGame/WartimePressCommittee/`（NextPage/Max模板） | `runtime_state/press_committee_plan.json` 由接收方当前实图生成；`config/press_committee_plan.example.json` 只是空结构，不是已学布局 |
| 有序专精与训练室观察 | `operator_training_v1/v2`、`operator_training_infrast_v1`，独立工具 `tools/run_operator_training_v1.py`；官方MAA的OperProgress/Training及对应资源 | `runtime_state/operator_training_plan.json`；`config/operator_training_plan.example.json` 默认禁用、无目标。队列、角色、技能及等级须来自接收方 |
| 模组只读与等级观察 | `operator_optional_inspection_v1`、`operator_readonly_locator_v1`、`scripts/operator_module_badge.py` | 接收方明确的角色/分支与当前图；读不清保持未知，不自动升级或花材料 |
| 黄票月度整包规划 | `voucher_exchange_plan_v1`，不调用实际交易 | 自己的 `runtime_state/voucher_exchange_policy.json` 和新鲜余额/已购档位；配置例默认禁用。规划成功不是已买 |
| 绿黄票底层原生能力 | `maa_utility_custom_v1.run(kind=...)` 调用所装MAA的Custom任务与模板 | 不挂默认日常；`native_completed_effect_pending` 只表示原生动作结束，必须另核库存/余额/档位，不能报购买完成 |

公开依赖由接收方从可信上游安装；官方MAA模板不重复分发。上述模块没有绕过原有 `selected_scope/admit`、当前任务、账号、资源限额、单控制者和关闭边界。只安装示例或运行离线探针不会启用真实业务。

模组执行Beta当前仅包含已验的 **怒潮凛冬 / HAM-X** 序列；这是支持范围，不是安装后的默认培养目标。将 [空模组计划例](../templates/operator-module-plan.example.json) 按自己的明确选择填成私有 `runtime_state/operator_module_plan.json`，分别选择观察、任务、解锁或升级，保留各步回执。其他角色/分支不会套用这个序列。

红票Beta读取独立私有 `runtime_state/red_catalyst_plan.json`，参考 [空购买计划例](../templates/red-catalyst-plan.example.json)。当前只支持明确请求的一件芯片助剂，核对90红票报价、账号/游戏包名和本次请求ID；未知结果先对账，不换运行目录重买。它不读取训练计划来决定购买账号，也不启用周期自动购买。具体命令和会话接法见随包原工具及其 `--help`。

## 本机配置与默认路径

`runtime/portable_paths.py` 只解析路径，不安装、不启动软件。MAA 默认使用当前用户的 `%LOCALAPPDATA%/MAA-App`，MuMu 默认使用当前机器 `%ProgramFiles%/Netease/MuMuPlayer-12.0`，Python 默认使用当前解释器，自研源码和输出以本包 runtime 目录为起点。实际安装到其他目录时，由接收方 AI 发现并传入覆盖值。

可用覆盖项：`ARKNIGHTS_MAA_PATH`（MAA.exe 或目录）、`ARKNIGHTS_MAA_ROOT`、`ARKNIGHTS_MUMU_ROOT`、`ARKNIGHTS_PYTHON`。游戏包和设备使用接收方确认的 `ARKNIGHTS_GAME_PACKAGE`、`ARKNIGHTS_DEVICE`；不要套用作者的 B 服、端口或模拟器实例编号。

`config/game_runtime_target_v1.json` 需要接收方根据真实 MuMu 实例生成；`config/local_ocr_v6_small_v1.json` 需要按已安装 OCR 环境与模型建立，所有相对路径以 `runtime/` 为根。按 [OCR 来源、安装与自检](local-ocr-setup.md) 填写真实 `base_python` 和隔离 `environment`，校验三个模型的 SHA-256，再调用现有 `preflight()`。已有示例仅供结构参考，不能把 `.example.json` 当成已生效的配置。游戏截图仍要求横屏 1920×1080，这是现有识别/坐标的实际前提。

签到、信赖、工坊及新版首页兼容识别所需参考图改为接收方自采，作者全屏和由其裁出的新模板均不随包。按 [运行资源边界](runtime-resources.md) 的界面、尺寸和裁框，使用 `python tools/collect_portable_resources_v1.py --kind <资源名> --source <自己的截图>`；工具只保留本机小裁片及指纹，不截图、不启动应用、不保留整屏。基建通知铃铛用 `--kind base_notification` 从接收方已安装 MAA 的 `resource/template/InfrastPic/Notification/InfrastNotification.png` 取得并检查指定上游指纹。另附原有不含账号标识的保全道具小图，它不是任何人的库存事实。

采集器在接收方本机 `recipient_resources/visual/` 和 `config/local_visual_resources_v1.json` 保存裁片与 SHA-256，消费者校验指纹、尺寸和格式，缺失/损坏/漂移不参与识别；这些本机文件不得加入公开包。新图须先人工确认并做自有正负例离线回放，指纹匹配不等于识别效果通过。不要手改固定地图、YW数据、官方通知模板或 OCR 的 SHA 常量，也不要把检查改为无条件通过；若上游内容变化，应按资源文档重新审查对应接口。

## 本次任务如何接上已有保护

作者工程的 `PROJECT_CONTRACT.json`、`.project-reasoning/AUTOMATION_HANDOFF.json`、`COMPONENTS.json` 和私人历史证据未公开。本机合同应按引擎 `validate_project_contract()` 与 `compile_execution_plan()` 的字段建立，并反映接收方用户真实目标；不得伪称源工程的历史验收在这台机器上已经通过。

每日接法保留 `selected_scope` 的外层适配位置。当前发布身份、实际源码指纹、接收方任务、资源规则和停止条件核对后，再进入 V146 组合。不要靠删除所有检查、忽略缺文件或无条件返回 PASS 来接通。

活动地图、接收方自己采集的小图及所需第三方资料，统一按 [runtime-resources.md](runtime-resources.md) 配置并验证。不要复制作者截图、账号进度或缺失文件时伪造通过。`release.json` 只供版本提示，不替代当前任务授权，也不自动更新执行文件。

肉鸽接法创建新的 `outputs/continuations/` 任务包及本机当前指针，保留 `admit()` 对任务路径、workflow、SHA、有效起止时间、主题和 artifact 指纹的校验。普通肉鸽任务的 `daily_replay`、`recording` 都为 false。队伍、分队、难度和截止来自接收方用户；源码中的既有默认预设需据此核对，不能当作新用户已选择。

共用的单控制者、MAA 队列归属、资源边界、失败分类、原步骤续接和结束清理仍沿用实际实现。AI 宿主消息/回复接口由接收方对接；`ark_host.cooperation_v1` 的事件与回复协议已在代码中，不要因为宿主不同就重做游戏流程。

## 本包验证范围

发布方检查源码来源、依赖清单、必要文件、路径改写、语法、隐私以及 ZIP 内容。接收方配置和自然运行结果属于接收方环境；本包不声称新电脑无需适配或已实机通过。接口对接成本不等于 Skill 缺少业务逻辑。
