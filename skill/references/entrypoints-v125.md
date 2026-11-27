# 选择任务、预览和运行
下面命令均在包内 `runtime` 目录执行。先按[安装说明](receiver-integration.md)配置本机。

```powershell
python ark.py list
python ark.py describe daily
python ark.py template daily
```

例如只要基建、公招、信用商店、任务领奖，把下面内容保存为 UTF-8 的 `日常.json`：

```json
{"modules":["base","recruit","mall","award"]}
```

```powershell
python ark.py plan daily --inputs 日常.json
python ark.py run daily --inputs 日常.json
```

自选日常按数组顺序执行；可用选项以 `describe daily` 的 selectable_modules 为准。仅查看干员模组无需指定干员；点名和入队不是一件事，见[模组示例](operator-and-voucher-interfaces.md)。`run daily` 不带参数才是默认日常。

已有模块会话用 `python ark.py status --output 原输出目录`；接续用 `resume --output 原输出目录 --check-only` 先读脚本的判断。明确追加另一目标用 `continue 目标 --output 原输出目录`；需要结束时用 `finish --output 原输出目录`。不要把这些命令当作每项必走的步骤。

更多例子：[模块如何组合](modular-architecture.md) · [日常与单项](workflows.md) · [只领奖或加点](progress-modules.md)。
