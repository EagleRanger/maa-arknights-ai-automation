# 接收方安装与配置

使用包内脚本，不需要作者工程、项目Loop或历史账号数据。

## 一次性准备

1. 安装MuMu、游戏并登录自己的账号；原始游戏截图横屏1920×1080。按实际MuMu CLI结果填写实例、安卓版本和游戏包，不抄作者端口。
2. 在完整包 `runtime/.runtime_maa/MAA-App/` 准备MAA程序、资源与自己的配置；不从作者机器复制账号配置。
3. 主Python需要Pillow、OpenCV、NumPy、psutil、uiautomation；独立v6-small环境和权重按[OCR说明](local-ocr-setup.md)配置。不再安装旧OCR引擎包。
4. 按[本机视觉资源](runtime-resources.md)采集自己的小模板；未知页面交当前执行AI，不复制作者完成缓存。
5. 从包内 `runtime/config/receiver_profile.example.json` 建立本机配置：账号称呼、游戏包、模拟器路径、Python及本账号排班。其它基建布局保留自己的方案，不强改333。可选培养／兑换只配置已选项。

## 启动

在完整包runtime目录，用已确认的Python执行：

```powershell
python ark.py init
python ark.py check
python ark.py check --task daily --probe
python ark.py run daily
```

前3项不启动游戏，probe会检查MAA资源可写性。init只生成本机运行绑定，不覆盖用户已改文件；升级时由本机AI按原[合并方式](release-notices-and-local-merge.md)处理。

## 单项与异常

从 `ark.py list/describe/template` 查业务目标；单项不重跑整日日常。`status`读原会话，`continue`追加目标，`finish`补收新增待办后退出。详细参数见[接口说明](entrypoints-v125.md)。

脚本不认识页面时保留原控制者，让执行AI看图接回；实际点击、页面恢复和任务完成分开核实。不要求先建第二个AI或监视任务。账号进度留在本地，资源沿已选计划，不从“每日”推导额外购买或培养。
