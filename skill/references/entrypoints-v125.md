# 业务目标与续接

工作目录为完整包的 `skill/runtime/`，使用本机配置的 Python。统一入口 `ark.py` 接收的是玩家目标，不是截图或点击步骤。默认日常仍调用原 V167 组合；已有战斗和导航算法不重写。

## 正常使用

```powershell
python ark.py list
python ark.py describe roguelike
python ark.py template roguelike
python ark.py run daily
python ark.py run roguelike --inputs inputs.json
python ark.py status --output <返回的本次目录>
python ark.py continue base --output <原目录>
python ark.py finish --output <原目录>
```

银凇只领奖的 `inputs.json` 是 `{"theme":"Sami","mode":"rewards"}`；没有选择加点或探索就不会执行它们。独立保全模块用 `python ark.py run sss`，内部沿本机作业串联编队、战斗、结算和周期领奖，不附带整日日常，不要求用户另下编队命令。其它目标参数用对应 `describe/template` 查看，不凭历史脚本名猜命令。

`run` 自动安排环境准备、内部步骤和过程记录，单项默认自动生成运行目录。普通模块执行返回后保留游戏，供同一个 AI 接回异常或执行下一个已授权目标。再次 `run` 普通单项目标时会复用匹配账号、版本和仍存活的公共会话；也可用 `continue` 明确指定原目录。已有结果或未知提交不重放。

`finish` 在普通会话内部补收新产生的基建、招募和任务待办，核验后再关闭。调用者不需要先列截图、准备、补领等步骤，也不需要手工提供收尾编号。不会因此重跑战斗、整日日常、轮班或无人机。

完整 `daily` 使用原日常 manifest 和报告；普通单项目标使用 `receipt.json`。`status` 读取实际结果和错误，不重新启动业务；`submitted_not_completed` 只表示命令送入原宿主，还要读同目录命令结果和业务证据。需要独立宿主的肉鸽刷经验、卫戍目标不会强插正在运行的普通会话。

## 自定义日常：选择模块，而不是重写程序

`daily`空参数仍走原默认组合。用户要改变选中模块或顺序时，AI填写以下`daily.json`后运行`python ark.py run daily --inputs daily.json`：

```json
{"modules":["base","recruit","mall","award"]}
```

模块按数组顺序执行，可选`startup/annihilation/event/farm/activity-rewards/base/recruit/mall/award/sss/training`。每项可为字符串或`{"task":"base","inputs":{"action":"routine"},"enabled":true}`。模块自己的任务参数沿同名业务目标；招募、信用商店等当前读取本机MAA配置，不接受未接入的临时参数。关闭项不会执行，空清单不会回退full。肉鸽长期/卫戍独立宿主不混入此清单，仍按各自业务目标调用。

这一组合沿已有普通模块会话，返回`receipt.json`；做完所选目标后AI调用`ark.py finish --output <原目录>`，由原补领环节处理新增待办再退出。依赖只检查所选模块，未选基建不要求基建配置；原默认日常及其manifest流程不变。`sequence`保留研发/兼容用途，不再要求普通自定义日常手拼内部步骤。

当前主线公共核验适配1—9章点名普通单关，AI可逐关续接明确范围；10章后层次切换/验收未接通时明确阻塞，不以默认层次替代。剿灭公共目标当前补齐已有代理的周进度，新剿灭首通找作业链仍待接入。卫戍阵容和难度尚未参数化，带自定义字段会拒绝，不能当默认策略已满足用户目标。

## 独立玩法宿主

- 肉鸽刷经验：目标 `roguelike`，`mode:experience`，当前持续宿主适配 `theme:Sami`；用户提供 `core_char`、`squad`、`roles`、带时区的 `deadline`。入口生成本机任务包并启动原 V9 宿主；不会复制作者的完成缓存或重新开发控制器。进度和异常接回按[肉鸽扩展](roguelike-mode-and-extension.md)及原 `tools/ark_cooperation_control.py --help`，不是普通会话的补领退出命令。日期必须来自当前任务，不照抄过期示例。
- 卫戍：目标 `stronghold`，入口准备 MAA 资源并安排原宿主执行一轮。进度、AI接回和结束仍沿 `tools/run_spa_trial_v1.py --output <原目录> --action ...`；`end` 结束原宿主，不能当成积分或清店完成。
- 模组与具名红票兑换：公共目标 `module/vouchers` 先读取本账号状态，Beta 未覆盖的步骤由执行 AI 在同一会话处理。报价、提交、回读属于内部辅助器，不再是玩家要逐项下达的任务。绿黄票完整购买、卫戍清店等尚未接通的能力不冒称自动完成。

## 只有异常时才用的配套

`python ark.py debug list` 查看内部操作；`debug describe <操作>` 查看来源和适用范围。正常任务不要求读内部目录、拼 `sequence` 或逐条提交截图。保留这些配套是为了接回和扩展，不是增加正常使用步骤。

保全编队的独立底层接口 `sss.formation` 保留在这里供内部测试/恢复，参数为region、job和本账号profile，不是普通功能菜单中的目标。正常保全始终调用完整sss模块，由原流程内部完成编队接战斗。

普通模块会话可用 `ark.py action --output <原目录> --json action.json`。动作文件示例：`{"action":"observe"}`、`{"action":"back"}`、`{"action":"home"}`、`{"action":"prepare"}`。点击为 `{"action":"tap","seq":3,"point":[100,200]}`，拖动为 `{"action":"swipe","seq":3,"start":[1200,500],"end":[600,500]}`。`seq` 来自刚看的新图；旧图、队列忙、另一运行身份或在途动作会拒绝，保留健康环境，不偷偷转完整日常。

同一会话 AI 先看新图，再操作实际可见控件；动作后核当前页面和效果。原日常输出自己的 run/event 时，沿原日常恢复口，而不是另开普通会话：先完成后台导航并取得新首页图，再用 `tools/ark_navigation_reply_v1.py --output <原合作目录> --run-id <真实run> --event-id <真实event> --screenshot <新首页原图> --note <实际特征>` 提交证明，核原 owner 继续原步骤。这个工具不点击，也不证明领奖。

已有兼容工程的同日续接沿[续接规则](continuity-and-signin.md)，先核实际效果，只补未完项。不能因为新入口更方便就再跑一遍 full。
