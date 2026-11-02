# V146 运行资源边界

本包只提供通用机制和下列明确公开的资源。不含作者账号、进度、偏好、暂停名单、日志、全屏截图或由作者截图裁出的新模板。资源可加载不等于接收机完整日常、游戏行为或自然稳定性验收通过；教学关代理逻辑仍为测试。

## 已随包的最小官方地图子集

`runtime/assets/maa_tl_20261101/MaaResource-TL-subset.zip` 来自 [MaaResource 固定提交](https://github.com/MaaAssistantArknights/MaaResource/tree/0b5acaf5fdaf76636739bb953882caff861223e1)。源归档 SHA-256 为 `CE56C6170B0DC5A09AF84BC31920935DFF6DE45BE661A81EE717746984EBC785`。

实际 `event_tl_route_v1.maps()` 读取 overview 后遍历全部 `stageId` 前缀 `act55side_`：因此闭包恰为 TL-1～TL-10、TL-TR-1 的 11 份地图 JSON、只保留这 11 行的 `overview.json`、原始 `LICENSE`，共 13 个 ZIP 成员。不包含其他活动、作业、图片、模型或二进制。地图 JSON 与源归档逐字节相同，overview 仅删去无关行，ZIP 容器重新构建；它不是上游完整归档。

子集 SHA-256 为 `34510776BC79138294EBF083D092ECB3462D0217CC2DD2644FC7A57794E1611C`；消费者硬校验这一值，漂移直接拒绝。逐成员哈希、用途和原始来源见同目录 `PROVENANCE.json`；完整 AGPL 许可证见 `LICENSE-AGPL-3.0.txt` 及 ZIP 内原 LICENSE。固定来源的 [上游 LICENSE](https://github.com/MaaAssistantArknights/MaaResource/blob/0b5acaf5fdaf76636739bb953882caff861223e1/LICENSE) 适用于此源格式子集；本包不将第三方数据宣称为原创或改成更宽松许可。

`event_tl_current_maps_v1` 仍先通过这一固定基线确认所需身份，再核接收方已安装的更新地图；不以旧字节覆盖合法的新地图，不放宽地图身份、网格、路径范围或冲突检查。安装目标仍是接收方自己配置的 MAA 资源目录，不能在 MAA 工作队列运行中更改。

`config/roguelike_tree_revisions.json` 仅包含通用 `Sami: sami-culture-43-v1` 版本标识，不含任何人已完成的事实。实际完成记录只由接收方账号和证据生成。

## 必须由接收方取得的本地小图

以下引用不随包。不要拷贝作者的 `runtime_screenshots`、MAA debug 图或历史测试夹具。使用自己的截图并人工核对界面及裁片，采集器只保留固定 ROI 小图，不保留整屏、不捕获屏幕、不启动游戏、不联网，也不自动判断“同款界面”。

以 `runtime/` 为当前目录，执行：

```powershell
python tools/collect_portable_resources_v1.py --kind signin_folded_v7 --source 'D:/自己的截图/home.png'
```

记录在本机 `recipient_resources/visual/<kind>.png` 和 `config/local_visual_resources_v1.json`。工具计算本机裁片和来源文件 SHA-256；加载器同时校验指纹、PNG、尺寸和资源名。既有资源不被覆盖。指纹只证明本机采集文件未变化，不能代替人工确认模板正确；先对自有正例和负例离线回放，再在获授权的自然流程验证。缺失、损坏或漂移即该模板不参与识别，不会推断奖励已领、免费、低信赖或允许盲点。

| `--kind` | 接收方需要的界面 | 原图尺寸 | 固定裁框 `(左,上,右,下)` |
| --- | --- | --- | --- |
| `signin_folded_v6` | 旧型首页活动折叠按钮 | 1920×1080 | `(0,137,20,180)` |
| `signin_expanded_v6` | 对应活动展开按钮 | 1920×1080 | `(373,49,444,86)` |
| `signin_folded_v7` | 下移型首页活动折叠按钮 | 1920×1080 | `(26,195,108,230)` |
| `workshop_zero` | 工坊当前费用蓝色数字 0 | 1920×1080 | `(1525,315,1595,370)` |
| `workshop_mood8` | 工坊消耗心情白色数字 8 | 1920×1080 | `(1725,315,1810,370)` |
| `trust_ascending` | 信赖升序的蓝色排序箭头 | 1920×1080 | `(1550,60,1600,90)` |
| `maa_home_2791` | MAA 设计基准首页圆箭头 | 1280×720 | `(286,387,315,411)` |

V6/V7 原匹配阈值、搜索范围、白色掩码、坐标计算保持不变，差异只在模板来自本机小图而非作者全屏。工坊/信赖也保持原掩码与阈值；OCR 可独立提供已核读数时仍沿原分支。

`maa_home_entry_compat_v2.py` 的七个入口标签也须自采。可一次读取你自己的 1280×720 首页（只输出七份裁片）：

```powershell
python maa_home_entry_compat_v2.py --source 'D:/自己的截图/maa-home-1280.png'
```

其 kind 为 `maa_home_entry_infrast/recruit/mall/task/depot/friends/terminal`（每项完整名称以采集器 `--help` 为准），裁框定义在 `portable_resources_v1.VISUAL_RECIPES`。不会自动缩放截图，也不会向 MAA 注册缺失的模板；原生模板及路线保留。没有新首页小图时兼容扩展标为 `recipient_reference_required`，不宣称新型界面已支持。

基建通知铃铛不需要作者截图，应从接收方已经安装的官方 MAA 中取得：

```powershell
python tools/collect_portable_resources_v1.py --kind base_notification --source 'D:/自己的MAA/resource/template/InfrastPic/Notification/InfrastNotification.png'
```

这里只接收原始 61×42 PNG，固定 SHA-256 `1D41DC2F6ACFF51DF647653EB3AF592900E366DF39C613C51B11394F27D5FCBF`。新版本文件若不同，不修改散列绕过，应重新审查原模板和识别行为；未取得这一版本时该窄识别保持未核验。工具不下载/安装 MAA。

**`recipient_resources/`、`config/local_visual_resources_v1.json` 及自有截图/日志都是本机资料，不能加入公开发布包。** 现有历史公开 `sss_delegate_card_v1` 的最小界面裁片沿原 NOTICE 保留，本次未从作者截图新增像素。

## YW 元数据不随包

`stage_sanity_cost_yw_v1/v3` 与 `yw_primary_material_v1` 需要准确 `recipient_resources/yw/catalog.json`，固定 SHA-256 `F0BE6E6663C6C75B08549FAEC9FEFD37A08475FF2B9AFC68EEFF0B838516E264`，缺失或漂移不放行相应费用/选关。未核得源游戏数据的明确分发许可，本包不重新分发该目录或候选作业。

接收方自行按上游许可/条款取得 [ArknightsGameData 固定提交的 excel 目录](https://github.com/Kengxxiao/ArknightsGameData/tree/17759cc8cdf37388414145d16262a3a06f3ab25e/zh_CN/gamedata/excel) 中 `activity_table.json`、`stage_table.json`、`zone_table.json`，放在自己的一个临时目录，然后离线重建：

```powershell
python tools/prepare_yw_catalog_local_v1.py --source-dir 'D:/自己的数据/yw-input'
```

工具不联网、不导入作业、不安装地图，只按既有筛选/序列化重建并检查完整固定 SHA。不匹配不写入；禁止用空目录、索引价格或删除校验代替。目录中的历史 source_urls 仅用于来源追踪，不代表采集器会请求这些作业或授予实战权限。

历史 `daily_yw_calendar_bridge_v1`、`daily_yw_expansion_route_v1`、`run_yw_stage_v1` 等仍需要接收方独立准备并准入的地图/作业 manifest、精确关卡身份与当前有效活动。它们不是“取得 catalog 即全部可用”；本包不附作者已准入清单，也不把已过期 YW 日历当作当前活动。接收方若再使用这些专项，须在原项目入口重新取得、核验并绑定自己的 manifest；缺失保持拒绝/未准入，不得复用作者的历史状态。

## 其他外部依赖与不随包内容

MAA/MuMu、ADB、Python 环境和 OCR 模型由接收方安装配置；本包不附安装程序、游戏、凭据或环境。PP-OCRv6 的固定 URL、SHA 和配置流程见 [local-ocr-setup.md](local-ocr-setup.md)。启动前仍会核模型、库版本及路径，未准备不能宣称完整入口通过。

完整入口还需要接收方自己的 `PROJECT_CONTRACT.json`、`.project-reasoning/AUTOMATION_HANDOFF.json`、`COMPONENTS.json`、账号实例绑定、资源上限和工作流选择；这些不能从作者机器复制。已安装 MAA 应提供 `config/gui.new.json`、`resource/tasks/tasks.json`、`resource/tasks/UiTheme/`、`resource/item_index.json`、`resource/Arknights-Tile-Pos/`、相关模板、MaaCore 等原文件。异常反馈线程、活动布局缓存、肉鸽/主线完成事实、商店/基建策略和运行回执均由接收方本机形成。

引擎还会读取接收方根目录的 `BUSINESS_RULES.json`，以及按已选能力需要的 `config/base_orundum_333_dynamic_v1.json`、基建库存/排班计划和相应 MAA 配置。示例只是结构参考，不能把作者策略或 `.example.json` 自动视为用户已批准。MuMu CLI、ADB、MaaCore/DirectML 等来自接收方官方安装；此资源适配未新增外部 PowerShell/批处理脚本依赖，也未自动下载这些程序。

视相博物馆特例只消费接收方的 `recipient_resources/museum/current_evidence.json`；作者的历史 `museum_evolution_20261024_evidence.json` 不随包。缺失时只回原通用分类，不把博物馆判成零理智，提供但损坏/身份不符仍拒绝。旧委托库存 V2 的参考帧只能由接收方显式设置 `ARKNIGHTS_DELEGATE_REFERENCE_FRAME`；未配置/不存在返回未识别，V3 的既有公共最小裁片另行保留。主线完成缓存、八房/物资事实也不以作者历史数据填充。

库存扫描缺少物品不能自动当作零。接收方确有当前扫描的零库存证据时，`recipient_zero_confirmations['30012']` 必须同时含 `value=0`（整型）、`authority='recipient_confirmation'`、`scan_sync_time` 精确等于本次 `depot.sync_time`；旧扫描确认不可沿用。

收到更新后先合并本地配置并更新自己的依赖指纹，不能直接用作者生产 registry/lock 让修改后的公开代码假装通过原封存检查。离线资源验证通过只证明包内闭包和自采加载接口，不证明这些外部条件已满足。
