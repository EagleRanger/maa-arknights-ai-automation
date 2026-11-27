# 按功能准备本地资源

只准备所选玩法用到的资源。下列公开地图附来源和许可证；账号进度和自采模板保存在本机。

## 已随包的最小官方地图子集

`runtime/assets/maa_tl_20261101/MaaResource-TL-subset.zip` 来自 [MaaResource 固定提交](https://github.com/MaaAssistantArknights/MaaResource/tree/0b5acaf5fdaf76636739bb953882caff861223e1)。源归档 SHA-256 为 `CE56C6170B0DC5A09AF84BC31920935DFF6DE45BE661A81EE717746984EBC785`。

子集含 TL-1～TL-10、TL-TR-1 的地图、索引和许可证；不是其他活动通用地图。

子集 SHA-256 为 `34510776BC79138294EBF083D092ECB3462D0217CC2DD2644FC7A57794E1611C`；消费者硬校验这一值，漂移直接拒绝。逐成员哈希、用途和原始来源见同目录 `PROVENANCE.json`；完整 AGPL 许可证见 `LICENSE-AGPL-3.0.txt` 及 ZIP 内原 LICENSE。固定来源的 [上游 LICENSE](https://github.com/MaaAssistantArknights/MaaResource/blob/0b5acaf5fdaf76636739bb953882caff861223e1/LICENSE) 适用于此源格式子集；本包不将第三方数据宣称为原创或改成更宽松许可。

`event_tl_current_maps_v1` 仍先通过这一固定基线确认所需身份，再核接收方已安装的更新地图；不以旧字节覆盖合法的新地图，不放宽地图身份、网格、路径范围或冲突检查。安装目标仍是接收方自己配置的 MAA 资源目录，不能在 MAA 工作队列运行中更改。

`config/roguelike_tree_revisions.json` 仅包含通用 `Sami: sami-culture-43-v1` 版本标识，不含任何人已完成的事实。实际完成记录只由接收方账号和证据生成。

## 必须由接收方取得的本地小图

需要相应功能时，从自己的游戏或 MAA 画面采集。采集器按表裁图，不会启动游戏。

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

`maa_home_entry_compat_v2.py` 的七个入口标签也须自采。可一次读取你自己的 1280×720 首页（只输出七份裁片）：

```powershell
python maa_home_entry_compat_v2.py --source 'D:/自己的截图/maa-home-1280.png'
```

其 kind 为 `maa_home_entry_infrast/recruit/mall/task/depot/friends/terminal`（每项完整名称以采集器 `--help` 为准），裁框定义在 `portable_resources_v1.VISUAL_RECIPES`。不会自动缩放截图，也不会向 MAA 注册缺失的模板；原生模板及路线保留。没有新首页小图时兼容扩展标为 `recipient_reference_required`，不宣称新型界面已支持。

基建通知铃铛取自本机已安装的 MAA：

```powershell
python tools/collect_portable_resources_v1.py --kind base_notification --source 'D:/自己的MAA/resource/template/InfrastPic/Notification/InfrastNotification.png'
```

这里只接收原始 61×42 PNG，固定 SHA-256 `1D41DC2F6ACFF51DF647653EB3AF592900E366DF39C613C51B11394F27D5FCBF`。新版本文件若不同，不修改散列绕过，应重新审查原模板和识别行为；未取得这一版本时该窄识别保持未核验。工具不下载/安装 MAA。

自采图、日志和模板清单属于本机配置，更新时保留。

## YW 元数据不随包

`stage_sanity_cost_yw_v1/v3` 与 `yw_primary_material_v1` 需要准确 `recipient_resources/yw/catalog.json`，固定 SHA-256 `F0BE6E6663C6C75B08549FAEC9FEFD37A08475FF2B9AFC68EEFF0B838516E264`，缺失或漂移不放行相应费用/选关。未核得源游戏数据的明确分发许可，本包不重新分发该目录或候选作业。

接收方自行按上游许可/条款取得 [ArknightsGameData 固定提交的 excel 目录](https://github.com/Kengxxiao/ArknightsGameData/tree/17759cc8cdf37388414145d16262a3a06f3ab25e/zh_CN/gamedata/excel) 中 `activity_table.json`、`stage_table.json`、`zone_table.json`，放在自己的一个临时目录，然后离线重建：

```powershell
python tools/prepare_yw_catalog_local_v1.py --source-dir 'D:/自己的数据/yw-input'
```

工具不联网、不导入作业、不安装地图，只按既有筛选/序列化重建并检查完整固定 SHA。不匹配不写入；禁止用空目录、索引价格或删除校验代替。目录中的历史 source_urls 仅用于来源追踪，不代表采集器会请求这些作业或授予实战权限。

目录只含费用与选材数据。活动必须仍有效；作业和地图需另外匹配，不能拿旧日历执行。

## 安装和账号数据

MAA、MuMu、Python、OCR 模型不随包安装，参见[本机接入](receiver-integration.md)及[OCR 配置](local-ocr-setup.md)。本机资源缺失时，只影响依赖它的能力。配置排班时使用自己的库存与布局；未知库存不要填零。确有本次扫描的零库存证据时，`recipient_zero_confirmations['30012']` 须含整数 `value=0`、`authority='recipient_confirmation'` 和与 `depot.sync_time` 相同的 `scan_sync_time`。
