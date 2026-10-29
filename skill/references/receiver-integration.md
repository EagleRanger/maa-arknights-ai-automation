# 接收方 AI：使用已有执行代码，按本机环境对接

本 Skill 同时提供方法说明和 `runtime/` 中的自研执行源码。它不是一键安装器：接收方 AI 应依据自己的宿主工具、电脑环境和用户目标完成对接。不要从说明重写已有的每日、主线、肉鸽领奖加点和异常续跑逻辑。

## 接收流程

1. 识别本机已有的 MAA、MuMu、Python 和 ADB。缺少的第三方软件、库、模型由接收方 AI 自行查找官方来源下载安装；本包不重复分发，也不维护安装链接清单。沿用其正常安装方式，不要求复制作者电脑的目录。
2. 使用当前宿主能够执行的 Python，按实际缺失情况补齐依赖。已知业务代码涉及 Pillow、opencv-python、numpy、psutil、uiautomation、rapidocr-onnxruntime；独立 OCR worker 另有 rapidocr、onnxruntime 和对应模型。先读 OCR 配置及 worker，不把两个 OCR 接口当成同一环境。无需预先完成所有软件版本的兼容矩阵。
3. 让用户自行安装游戏并登录自己的账号。AI 不需要接收密码、验证码或作者的登录数据，也不增加额外身份认证。安装后只检查执行所需的路径、模块、模拟器连接和截图尺寸；不为证明安装而强制打一局或消耗游戏资源。
4. 从接收方当前用户目标建立本机配置和本次任务。首次运行保留空的账号进度、完成缓存和运行记录；不能把作者已通关、已领奖、过期任务或已停止的队列当作接收方事实。
5. 选择下面的已有业务入口，对接本机工具后按用户原任务运行。遇到环境差异只修对应接口；真实效果仍由原游戏画面、队列日志和结果记录核对。

## 现成代码从哪里调用

| 能力 | 现有实现与接缝 |
| --- | --- |
| 每日完整业务组合 | `run_daily_v120.full()`，它复用前序已实现模块；不能只取 V120 一个文件。 |
| 每日的外层任务绑定 | `daily_dispatch_v1.selected_scope(selected, checked)`。用当前发布文件清单、接收方当前任务和目标核验生成绑定；旧 `preflight()` 依赖作者生产登记，不直接照搬。 |
| 主线推进与通用引擎 | `arknights_daily_runtime_v12.py` 的 `mode_mainline()` 等函数；共用环境、识别、独占和清理从 `ark_host` 装配。 |
| 独立模块组合 | `ark_modules.assembly`、`ark_modules.operations`、`ark_modules.runtime_session`；面向已经准备好的 runtime，不默认升级为完整每日任务。 |
| 银凇肉鸽监督、领奖、加点、异常协作 | `run_sami_progress_v2.main()` 复用 V1 与 `run_sami_until_deadline`。V1 的 `admit()` 消费新的本次任务包，V2 在这层之上安装协作逻辑。 |
| 其他主题和功能 | 由 `runtime/` 内既有域模块和引擎实现，参见对应功能文档；当前银凇接法不等于所有主题均经新机器实跑。 |

`runtime/SOURCE_MANIFEST.json` 记录发布源码的路径与 SHA-256。首次对接核对包内容，修改后为接收方自己的版本记录新指纹。新版本身份不表示已经完成游戏实测。

## 本机配置与默认路径

`runtime/portable_paths.py` 只解析路径，不安装、不启动软件。MAA 默认使用当前用户的 `%LOCALAPPDATA%/MAA-App`，MuMu 默认使用当前机器 `%ProgramFiles%/Netease/MuMuPlayer-12.0`，Python 默认使用当前解释器，自研源码和输出以本包 runtime 目录为起点。实际安装到其他目录时，由接收方 AI 发现并传入覆盖值。

可用覆盖项：`ARKNIGHTS_MAA_PATH`（MAA.exe 或目录）、`ARKNIGHTS_MAA_ROOT`、`ARKNIGHTS_MUMU_ROOT`、`ARKNIGHTS_PYTHON`。游戏包和设备使用接收方确认的 `ARKNIGHTS_GAME_PACKAGE`、`ARKNIGHTS_DEVICE`；不要套用作者的 B 服、端口或模拟器实例编号。

`config/game_runtime_target_v1.json` 需要接收方根据真实 MuMu 实例生成；`config/local_ocr_v6_small_v1.json` 需要按已安装 OCR 环境与模型建立。已有示例仅供结构参考，不能把 `.example.json` 当成已生效的配置。游戏截图仍要求横屏 1920×1080，这是现有识别/坐标的实际前提。

源码使用的两张全屏参考图（折叠主页、干员信赖排序页）含原账号状态，未随包分发；对应功能需要时，在接收方已登录的相同界面采集到 `assets/event_signin/home_folded_20261024.png` 与 `assets/activity_room_visual_v1/trust_ascending_reference.png`。文件名是既有代码引用名，不表示接收方沿用旧日期的任务或进度。基建通知模板可从接收方 MAA 的 `resource/template/InfrastPic/Notification/InfrastNotification.png` 取得，并供源码期待的 `assets/vision/base_notification_v1/` 使用。另附不含账号信息的保全道具识别小图；它不是作者的库存记录。

替换参考图时，同时检查对应模块的参考图 SHA 常量及配置，按接收方新图更新指纹并验证原识别规则；仅把新图放进同名路径不会自动通过旧指纹检查。保留图像内容与识别效果核验，不把哈希检查改为无条件通过。

## 本次任务如何接上已有保护

作者工程的 `PROJECT_CONTRACT.json`、`.project-reasoning/AUTOMATION_HANDOFF.json`、`COMPONENTS.json` 和私人历史证据未公开。本机合同应按引擎 `validate_project_contract()` 与 `compile_execution_plan()` 的字段建立，并反映接收方用户真实目标；不得伪称源工程的历史验收在这台机器上已经通过。

每日接法保留 `selected_scope` 的外层适配位置。当前发布身份、实际源码指纹、接收方任务、资源规则和停止条件核对后，再进入原 V120 组合。不要靠删除所有检查、忽略缺文件或无条件返回 PASS 来接通。

肉鸽接法创建新的 `outputs/continuations/` 任务包及本机当前指针，保留 `admit()` 对任务路径、workflow、SHA、有效起止时间、主题和 artifact 指纹的校验。普通肉鸽任务的 `daily_replay`、`recording` 都为 false。队伍、分队、难度和截止来自接收方用户；源码中的既有默认预设需据此核对，不能当作新用户已选择。

共用的单控制者、MAA 队列归属、资源边界、失败分类、原步骤续接和结束清理仍沿用实际实现。AI 宿主消息/回复接口由接收方对接；`ark_host.cooperation_v1` 的事件与回复协议已在代码中，不要因为宿主不同就重做游戏流程。

## 本包验证范围

发布方检查源码来源、依赖清单、必要文件、路径改写、语法、隐私以及 ZIP 内容。接收方配置和自然运行结果属于接收方环境；本包不声称新电脑无需适配或已实机通过。接口对接成本不等于 Skill 缺少业务逻辑。
