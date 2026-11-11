# 接收方本机安装与配置

目标是使用已经附带的脚本，不是让接收AI重新开发方舟控制器。你不需要作者的工程、项目Loop、总Loop、私有组件表或历史账号状态。

## 一次性准备

1. 用户本机安装MuMu12、游戏并登录自己的账号；AI不需要密码或验证码。游戏原始截图为横屏1920×1080。根据真实MuMu CLI `info -v all`结果填写`config/game_runtime_target_v1.json`的`created_timestamp`、`android_version`和`package`，不要使用作者端口/实例。
2. 在本包`runtime/.runtime_maa/MAA-App/`准备匹配的MAA程序、资源和自己的配置：`MAA.exe`、`MAA.dll`、`MaaCore.dll`、`config/gui.new.json`、`resource/tasks/tasks.json`和`resource/item_index.json`。不重复分发MAA，不从作者机器复制。公开`check --probe`会验证文件/可写性和目标实例，不启动业务。
3. 配置能运行本包的Python与业务库：Pillow、OpenCV、NumPy、psutil、uiautomation及原RapidOCR接口。独立V6-small OCR按[固定来源与自检](local-ocr-setup.md)安装对应环境、库和三个模型，填写`config/local_ocr_v6_small_v1.json`；不要把模型名当库版本。
4. 按[本机视觉资源](runtime-resources.md)采集自己页面的小模板。已有采集工具`tools/collect_portable_resources_v1.py`负责裁剪/尺寸/指纹；不复用作者截图、库存、已领奖或完成缓存。未覆盖页面由AI按实图接回，不假填模板成功。
5. 参照`config/receiver_profile.example.json`生成自己的`config/receiver_profile.json`。必填`account_key`（本机账号称呼）、`game_package`、`mumu_root`、`python`；`base_plan`指向本账号实际排班。本包默认动态生产政策沿既有四档333格式，示例为`base_orundum_333_dynamic_v1.example.json`，需按本机实际房间/干员调整；其它布局保留原方案，让本机AI接入对应策略，不直接套成333。游戏包须与目标文件一致。培养、模组、凭证等可选计划仍按对应文档填写，未选功能不阻塞其它单项。

安装公开依赖由接收方AI从可信上游处理；这些条件不是要求玩家看代码。`python`命令替换为已确认的解释器即可，不反复搜索裸Python。初始化前核用户当前任务，正常准备不需要逐步重复授权。

## 建立运行绑定

```powershell
python ark.py init
python ark.py check
python ark.py check --task daily --probe
python ark.py run daily
```

前三条不启动游戏；`--probe`包含MAA资源临时写入探针，不是严格只读。最后一条才执行真实每日任务。

`init`根据本机配置生成`PROJECT_CONTRACT.json`、`BUSINESS_RULES.json`及旧运行链需要的本机handoff元数据，并记录生成文件指纹；不是复制作者的验证历史，不建立另一个项目Loop，也不把本机标成已实测。公开接入使用`SOURCE_MANIFEST.json`核实际源码，继续通过既有`selected_scope`装配V167，原游戏控制权、资源检查、结果核验和异常接回仍在。

已有工程或用户已改文件不覆盖；提示具体差异后，由该用户AI决定如何合并。代码升级不在运行中自动下载或重建基线，不自动修改凭据、账号进度、原生定时任务或模型选型。原兼容dispatcher保留。

## 单项、组合和异常

正常业务目标的命令统一从`ark.py list/describe/template`取得；每项不需要接收AI再写宿主。截图、OCR、准备和核验是模块内部配套，不是玩家任务。普通目标使用同一个环境/控制器，返回结果后保活；AI用`status`查看结果，追加目标用`continue <业务目标>`，结束用`finish`，脚本自行补收新增待办再关闭，不要求手工拼收尾。只有异常接回或研发才查内部操作目录。参数格式见[接口说明](entrypoints-v125.md)；[源码能力表](capability-map.md)仅供需要时定位已有实现。

第一次运行、新页面和新版本仍以实际游戏效果核验。错误消息区分缺配置、未知页面、业务失败和已提交但未核验，不因一个OCR字形或弹层退出整日。需要看图就交当前执行AI；平台没有跨对话工具也可在同一对话处理，不要求先建“项目AI”或额外监视任务。

账号数据只保存在自己的`runtime_state/accounts/`等本机状态目录；公共包只带机制和空示例。默认本机公共入口仅现有理智、无源石药剂；票据/模组材料必须在对应具名用户计划内，不能从“每日”推导额外购买或培养授权。
