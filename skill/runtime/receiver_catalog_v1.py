"""Internal operation registry. Public callers choose receiver_goals_v1 goals."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Capability:
    id: str
    summary: str
    implementation: str
    inputs: tuple = ()
    maturity: str = 'existing'
    route: str = 'session'
    notes: str = ''


TASKS = (
    Capability('goal.event', '活动推进目标的内部编排', 'receiver_operations_v1:extra'),
    Capability('goal.event_farm', '活动刷取目标的内部编排', 'receiver_operations_v1:extra'),
    Capability('goal.base', '基建管理目标的内部编排', 'receiver_operations_v1:extra'),
    Capability('goal.activity_rewards', '活动奖励目标的内部编排', 'receiver_operations_v1:extra'),
    Capability('goal.module', '模组养成目标的内部编排', 'receiver_operations_v1:extra'),
    Capability('goal.red_catalyst', '具名红票兑换目标的内部编排', 'receiver_operations_v1:extra'),
    Capability('daily.full', '完整日常：周剿灭、活动/刷取、基建招募领奖和收尾',
        'run_daily_v167:full', route='daily', notes='复用原发布组合；不以单项任务代替完整日常'),
    Capability('daily.custom', '按用户选择的模块、参数与顺序组合日常',
        'receiver_goals_v1:daily_steps', ('modules',), notes='复用原模块会话；结束用finish补收新增待办，不回退full'),
    Capability('weekly.annihilation', '本周剿灭、首通和奖励核验', 'ark_modules.domains.weekly:weekly'),
    Capability('activity.stage', '活动普通/EX/突袭逐关作业与结果核验', 'ark_modules.domains.activity:stage', ('event', 'stage', 'layer')),
    Capability('activity.farm', '按实时理智和库存刷活动材料', 'ark_modules.domains.farming:farm', ('event',)),
    Capability('activity.rewards', '活动任务奖励核验与领取', 'ark_modules.domains.activity:rewards', ('event',)),
    Capability('activity.press', '战时新闻委员会逐份检查和处理', 'event_press_committee_v2:service', maturity='event-specific'),
    Capability('activity.signin', '当期签到/许愿墙弹层与首页入口处理', 'event_signin_discovery_v6:service',
        notes='通过已有首页导航链处理当前有效活动；不存在的活动跳过'),
    Capability('mainline.stage', '指定主线关卡推进', 'ark_modules.domains.mainline:mainline', ('stage', 'layer', 'max_attempts')),
    Capability('resource.farm', '用户明确指定的资源关刷取', 'ark_modules.domains.farming:resource', ('stage', 'times')),
    Capability('periodic.sss', '保全编队、作业和本周期领奖', 'ark_modules.domains.periodic:sss'),
    Capability('sss.formation', '只完成保全20人编队，不开战', 'arknights_daily_runtime_v12:_configure_sss_formation',
        ('region', 'job', 'profile'), notes='内部导航至该区域准备/编队页；名单来自用户账号/作业，不中止已有委托、不开始战斗'),
    Capability('base.prepare', '按本机生产目标和库存生成基建排班', 'ark_modules.domains.base:prepare_base'),
    Capability('base.infrast', '只执行并核验基建链', 'ark_modules.daily_tasks:PreparedDailyQueue',
        notes='需要先执行base.prepare；不会附加招募或商城链'),
    Capability('base.drones', '按生产目标和升级预留使用无人机', 'ark_modules.domains.base:drones', ('target',)),
    Capability('base.room.trust', '一个空活动室安排未满信赖干员', 'run_activity_room_service_v1:service', ('position',)),
    Capability('base.room.upgrade', '活动室升级与材料计划', 'activity_room_upgrade_v1',
        maturity='beta-interface', route='extension', notes='升级报价、合成、逐级核验使用该接口；当前无通用自动整套宿主'),
    Capability('daily.startup', '只执行启动/登录配给链', 'ark_modules.daily_tasks:PreparedDailyQueue'),
    Capability('daily.recruit', '只执行公开招募链', 'ark_modules.daily_tasks:PreparedDailyQueue'),
    Capability('daily.mall', '只执行信用商店链', 'ark_modules.daily_tasks:PreparedDailyQueue'),
    Capability('daily.award', '只执行任务奖励链', 'ark_modules.daily_tasks:PreparedDailyQueue'),
    Capability('daily.final', '已准备环境中的五链日常组合', 'ark_modules.domains.daily:daily'),
    Capability('daily.collect', '追加任务后只收新增基建/招募/任务待办', 'ark_modules.domains.daily:exit_tail'),
    Capability('roguelike.inspect', '只观察指定肉鸽主题的永久进度', 'permanent_progress_modules_v1:run', ('theme',)),
    Capability('roguelike.rewards', '只领指定肉鸽已累计积分奖励', 'permanent_progress_modules_v1:run', ('theme',)),
    Capability('roguelike.growth', '只处理指定肉鸽永久加点，已满跳过', 'permanent_progress_modules_v1:run', ('theme',),
        notes='新主题未覆盖加点布局时保留页面交AI；不开始探索'),
    Capability('roguelike.explore', '按主题运行MAA肉鸽探索', 'arknights_daily_runtime_v12:mode_roguelike', ('theme',),
        notes='本接口为原生单次任务，不代替长期V9宿主；主题支持以本机MAA为准'),
    Capability('roguelike.long', '银凇持续刷经验、结算后领奖加点、截止交接', 'tools/start_roguelike_owner_v3.py',
        ('core_char', 'squad', 'roles', 'deadline'), route='tool', notes='自动生成本机任务包，当前最高已解锁难度；不借作者历史'),
    Capability('roguelike.watch', '重点败关截图和建议/策略扩展接口', 'roguelike_battle_watch_v1:boundary',
        route='extension', notes='挂在探索宿主，不是单独启动第二个监视器'),
    Capability('reclamation.rewards', '生息演算繁荣点数领奖/兑换页核验', 'permanent_progress_modules_v1:run',
        notes='兑换商品选择未覆盖时交AI，不套肉鸽一键领取'),
    Capability('reclamation.run', '按明确轮数运行生息演算刷分', 'arknights_daily_runtime_v12:mode_reclamation', ('cycles',)),
    Capability('spa.badges','卫戍协议刷角标（待测试）','stronghold_badges_trial_v1:run',maturity='beta'),
    Capability('spa.trial', '新版卫戍协议一轮刷分、教学接回和结果观察', 'tools/run_spa_trial_v1.py',
        route='tool', notes='已有独立宿主；不包含自动清空功勋商店'),
    Capability('spa.rewards.inspect', '卫戍功勋商店和累计奖励只读识别', 'spa_rewards_state_v1',
        route='extension', notes='与spa.trial同一宿主观察；自动兑换仍待接入'),
    Capability('operator.paradox', '自动选择并执行一个尚未通过的悖论模拟', 'paradox_simulation_v1:one_module', maturity='beta'),
    Capability('operator.modules','所选干员与分支的模组队列','operator_module_queue_v1:one_module',maturity='beta'),
    Capability('operator.training', '指定干员有序专精，保留忙碌训练室', 'operator_training_v2:service', maturity='beta'),
    Capability('operator.module.inspect', '先读取干员模组实际进度', 'operator_module_missions_v1:inspect', maturity='beta'),
    Capability('operator.module.mission', '指定模组任务作业并回读计数', 'operator_module_missions_v2:run', ('job',), maturity='beta'),
    Capability('operator.module.unlock', '具名模组报价后提交解锁', 'tools/module_unlock_trial.py',
        maturity='beta', route='session-tool', notes='目前只适配怒潮凛冬HAM-X；先由AI到已核报价页'),
    Capability('operator.module.upgrade', '具名模组逐级升级并核验', 'tools/module_upgrade_trial.py', ('level',),
        maturity='beta', route='session-tool', notes='目前只适配怒潮凛冬HAM-X；目标2/3级，需新鲜前级页和报价'),
    Capability('vouchers.inspect', '只读绿票/黄票/红票商店状态', 'operator_optional_inspection_v1:vouchers'),
    Capability('vouchers.yellow.plan', '整套黄票寻访券月度预算规划，不购买', 'voucher_exchange_plan_v1:service', route='offline'),
    Capability('vouchers.green.native', 'MAA绿票原生兑换执行接口', 'maa_utility_custom_v1:run',
        maturity='beta-interface', route='extension', notes='本版未接完整预算/购买后核验，不纳入自动花票命令'),
    Capability('vouchers.yellow.native', 'MAA黄票原生兑换执行接口', 'maa_utility_custom_v1:run',
        maturity='beta-interface', route='extension', notes='先规划整套余额；原生结束不等于购买闭环'),
    Capability('vouchers.red.submit', '只提交一件90红票芯片助剂', 'tools/red_catalyst_trial.py',
        maturity='beta', route='session-tool', notes='先配置明确请求ID/账号，并到已核红票商品报价页'),
    Capability('vouchers.red.verify', '回读同次芯片助剂余额下降和库存增加', 'tools/red_catalyst_trial.py',
        maturity='beta', route='session-tool'),
    Capability('tutorial.ai', '教学关由AI按实图提示操作', 'tutorial_ai_handoff_v2',
        maturity='ai-assisted', notes='使用同一会话的observe/tap/swipe；不是虚构的通用自动通关'),
    Capability('navigation.home', '只返回并核验首页', 'arknights_daily_runtime_v12:goto_main_menu'),
    Capability('observe', '截图/OCR，供AI判断当前页面', 'operator_optional_inspection_v1:frame'),
)
BY_ID = {row.id: row for row in TASKS}
CHAINS = {'daily.startup': 'StartUp', 'base.infrast': 'Infrast', 'daily.recruit': 'Recruit',
          'daily.mall': 'Mall', 'daily.award': 'Award'}


def describe(task=None):
    rows = TASKS if task is None else (BY_ID[task],)
    return [dict(asdict(row), command=('python ark.py debug describe ' + row.id if row.route == 'extension'
        else 'python ark.py debug run ' + row.id + ' --inputs <本机参数JSON> --output <outputs/本次目录>'),
        callable=row.route != 'extension') for row in rows]


def validate(task, inputs):
    if task not in BY_ID:
        raise ValueError('没有这个任务；运行 python ark.py list 查看现有功能：' + task)
    row = BY_ID[task]
    if row.route == 'extension':
        raise ValueError('这是扩展/待接入接口，不冒称自动执行：' + row.implementation + '；' + row.notes)
    if not isinstance(inputs, dict):
        raise ValueError('inputs 必须为 JSON 对象')
    missing = [name for name in row.inputs if name not in inputs]
    if missing:
        raise ValueError('本任务缺参数：' + ', '.join(missing))
    if task == 'operator.paradox' and inputs:raise ValueError('悖论单关不接收点名、次数或培养参数')
    if task=='spa.badges':
        from stronghold_badges_trial_v1 import params
        params(inputs)
    if task=='operator.modules' and inputs:raise ValueError('队列只取本人计划；更改目标用选择器')
    if task == 'daily.full' and inputs:
        raise ValueError('日常默认组合使用本机配置；特调请使用明确模块计划')
    if task == 'activity.stage' and inputs['layer'] not in ('normal', 'challenge'):
        raise ValueError('活动layer为normal或challenge；EX用对应关卡编号，不猜层次')
    if task == 'mainline.stage' and (inputs['layer'] not in ('normal', 'hard') or
            type(inputs['max_attempts']) is not int or not 1 <= inputs['max_attempts'] <= 5):
        raise ValueError('主线layer为normal/hard，max_attempts为1到5')
    if task.startswith('roguelike.') and task not in ('roguelike.long', 'roguelike.watch'):
        if inputs.get('theme') not in ('Phantom', 'Mizuki', 'Sami', 'Sarkaz', 'JieGarden', 'BlackFlow'):
            raise ValueError('请选择目录中已适配的肉鸽主题')
    return row
