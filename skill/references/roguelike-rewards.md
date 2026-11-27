# 肉鸽：领奖、加点、刷经验
从 `runtime` 运行 `python ark.py template roguelike`。例如参数文件 `肉鸽.json` 写 `{"theme":"Mizuki","mode":"rewards"}`，再运行 `python ark.py run roguelike --inputs 肉鸽.json`。只加点把 mode 改为 `growth`。要刷经验见[探索模式](roguelike-mode-and-extension.md)，不把领奖请求改成开新局。

| theme | 积分奖励 | 永久加点 | 点数 |
| --- | --- | --- | --- |
| Phantom | 古堡笔记 | 幕后筹备 | 晦暗的灵感 |
| Mizuki | 生态谱系 | 认知塑造 | 主观想象 |
| Sami | 科考记录 | 文化比较 | 理性视阈 |
| Sarkaz | 假说辑录 | 历史重构 | 散佚迷思 |
| JieGarden | 游园纪念 | 学识古今 | 失落智识 |
| BlackFlow | 源流堆栈 | 生命游戏 | 演化算子 |

奖励等级满不代表树已点满；例如水月以认知塑造页的“认知完备”判永久完成。点数为零只代表现在不能点，不能当成全树已满。加点在结算或主题主页处理，按升级按钮及点数变化核实；永久完成记录只对本账号、主题和当前树版本有效。新主题未识别时不套用另一主题的坐标。

生息演算另用 `python ark.py run reclamation` 领取已有繁荣奖励。刷分用 mode=score 并指定 cycles；需要选择兑换且未适配时由 AI 按当前余额和玩家目标接手，不为测试开局或删档。
