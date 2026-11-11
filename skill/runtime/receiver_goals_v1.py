"""Human goals are the public interface; mechanical steps stay internal."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Goal:
    id: str
    summary: str
    template: dict
    notes: str = ''


GOALS = (
    Goal('daily', '完成默认日常或按所选模块、参数和顺序执行自定义日常', {},
         '空参数沿原默认日常；自定义用modules数组，例如["base","recruit","mall","award"]，不夹带未选业务'),
    Goal('annihilation', '通过已有代理补齐本周剿灭奖励', {}, '当前公共绑定不含新剿灭自动找作业首通链；遇到未400交AI，不冒称已接通'),
    Goal('event', '推进当前活动已开放关卡和附加内容，最后领奖',
         {'event': '', 'include_challenge': True}, '可省略活动名让脚本发现；不自动把推图目标替换成芯片'),
    Goal('farm', '刷指定活动材料或明确指定的资源关',
         {'kind': 'event', 'event': ''}, '资源关使用kind=resource，并填写stage和times'),
    Goal('activity-rewards', '领取当前活动签到、许愿墙和任务奖励',
         {'event': ''}, '只处理当前有效活动；没有活动不阻塞，不开始战斗'),
    Goal('base', '按本机方案管理基建、生产和轮班',
         {'action': 'routine'}, 'action也可为trust（指定空活动室）或drones（当前生产目标）'),
    Goal('sss', '完成保全派驻和本周期奖励', {},
         '独立保全模块；按本机作业内部串联编队、战斗、结算和周期领奖'),
    Goal('roguelike', '肉鸽刷经验并在结算后领奖加点，或只处理已有奖励/加点',
         {'theme': 'Sami', 'mode': 'rewards'},
         'mode为experience/rewards/growth；银凇持续刷经验需core_char、squad、roles、deadline'),
    Goal('reclamation', '生息演算刷分或领取已有繁荣奖励',
         {'mode': 'rewards'}, '刷分mode=score并指定cycles；未覆盖兑换选择交AI'),
    Goal('stronghold', '新版卫戍协议刷取一轮积分并核验结果', {}, '沿原单轮宿主；不冒称已能自动清店'),
    Goal('training', '按指定干员和顺序完成技能专精培养', {},
         '使用本机培养计划；忙碌训练室保留，真实等级完成才推进，Beta'),
    Goal('module', '处理指定干员模组任务、解锁和目标等级',
         {'action': 'inspect'}, 'develop需operator/module/target_level；先读实际进度，当前升级Beta仅怒潮凛冬HAM-X'),
    Goal('vouchers', '凭证商店观察、整套黄票规划或具名红票兑换',
         {'action': 'inspect'}, 'action为inspect/plan-yellow/chip-catalyst；绿黄票完整自动购买仍待接入'),
    Goal('mainline', '推进用户指定的主线目标关卡',
         {'stage': '', 'layer': 'normal', 'max_attempts': 5},
         '当前公开核验适配第1至9章点名普通单关；范围由AI逐关调用，不自动重扫旧主线。高章难度切换尚未接入，不用默认层次替代'),
)
BY_GOAL = {g.id: g for g in GOALS}


def describe(goal=None):
    rows = GOALS if goal is None else (BY_GOAL[goal],)
    output = [dict(asdict(g), command='python ark.py run ' + g.id +
        (' --inputs <目标参数JSON>' if g.template else ''),
        internal_steps='脚本自行安排；截图/OCR/准备/返回/提交/核验不是用户任务') for g in rows]
    for row in output:
        if row['id'] == 'daily':
            row.update(custom_command='python ark.py run daily --inputs <日常模块JSON>',
                selectable_modules=list(DAILY_MODULES),
                custom_example={'modules': ['base', 'recruit', 'mall', 'award']},
                module_parameters='每项可为task字符串或{task,inputs,enabled}；只执行启用项并保留数组顺序。默认MAA参数沿本机配置，不默默忽略未支持的临时参数。',
                finish='自定义组合复用原模块会话；AI完成所选目标后调用finish，内部补收新增待办再退出')
        if row['id'] == 'stronghold':
            row['unsupported_options'] = '当前宿主未接入自定义干员/难度；带此类参数会明确拒绝，不执行默认策略替代'
    return output


def compile_goal(goal, inputs):
    """Translate intent to existing operations, without asking AI to assemble."""
    if goal not in BY_GOAL or not isinstance(inputs, dict):
        raise ValueError('请选择list中的业务目标，参数为JSON对象')
    value = dict(inputs)
    if goal == 'daily':
        if not value:
            return 'daily.full', {}
        if set(value) != {'modules'}:
            raise ValueError('自定义日常使用modules数组；每项可为任务名或{task,inputs,enabled}，不回退完整日常')
        daily_steps(value['modules'])
        return 'daily.custom', value
    if goal == 'stronghold' and value:
        raise ValueError('当前卫戍单轮宿主尚未接入自定义阵容/难度参数；不丢弃用户选择后执行默认策略')
    direct = {'annihilation': 'weekly.annihilation',
              'stronghold': 'spa.trial', 'training': 'operator.training', 'mainline': 'mainline.stage'}
    if goal in direct:
        return direct[goal], value
    if goal == 'event':
        return 'goal.event', value
    if goal == 'activity-rewards':
        return 'goal.activity_rewards', value
    if goal == 'base':
        action = value.pop('action', 'routine')
        task = {'routine': 'goal.base', 'trust': 'base.room.trust', 'drones': 'base.drones'}.get(action)
        if not task:
            raise ValueError('基建目标为routine/trust/drones；整套活动室升级仍为扩展接口')
        return task, value
    if goal == 'sss':
        if value.pop('formation_only', False) is not False:
            raise ValueError('仅编队为内部调试接口，不自动把旧仅编队请求改成战斗；公共sss执行完整保全流程')
        return 'periodic.sss', value
    if goal == 'farm':
        kind = value.pop('kind', 'event')
        if kind not in ('event', 'resource'):
            raise ValueError('刷取kind为event或resource')
        return ('goal.event_farm' if kind == 'event' else 'resource.farm'), value
    if goal == 'roguelike':
        mode = value.pop('mode', 'experience')
        if mode == 'experience':
            if value.pop('theme', 'Sami') != 'Sami':
                raise ValueError('当前公共持续刷分宿主适配Sami；其他主题通过已有原生接口/AI扩展，不擅自换主题')
            return 'roguelike.long', value
        if mode not in ('rewards', 'growth'):
            raise ValueError('肉鸽mode为experience/rewards/growth')
        return 'roguelike.' + mode, value
    if goal == 'reclamation':
        mode = value.pop('mode', 'rewards')
        if mode not in ('rewards', 'score'):
            raise ValueError('生息演算mode为rewards或score')
        return ('reclamation.rewards' if mode == 'rewards' else 'reclamation.run'), value
    if goal == 'module':
        action = value.pop('action', 'inspect')
        if action == 'inspect':
            return 'operator.module.inspect', value
        if action != 'develop' or any(name not in value for name in ('operator', 'module', 'target_level')):
            raise ValueError('模组养成须明确develop及operator/module/target_level；只检查用inspect')
        if (value['operator'], value['module']) != ('怒潮凛冬', 'HAM-X'):
            raise ValueError('当前具名模组升级Beta仅适配怒潮凛冬HAM-X，不替换用户目标')
        if type(value['target_level']) is not int or not 1 <= value['target_level'] <= 3:
            raise ValueError('模组目标等级为1到3，先核实际进度')
        return 'goal.module', value
    if goal == 'vouchers':
        action = value.pop('action', 'inspect')
        task = {'inspect': 'vouchers.inspect', 'plan-yellow': 'vouchers.yellow.plan',
                'chip-catalyst': 'goal.red_catalyst'}.get(action)
        if not task:
            raise ValueError('凭证目标为inspect/plan-yellow/chip-catalyst；不把未接通的绿黄票自动购买冒称可执行')
        return task, value
    raise ValueError('业务目标尚未接入')


DAILY_MODULES = {
    'startup': ('daily.startup', None),
    'annihilation': ('weekly.annihilation', None),
    'event': (None, 'event'),
    'farm': (None, 'farm'),
    'activity-rewards': (None, 'activity-rewards'),
    'base': (None, 'base'),
    'recruit': ('daily.recruit', None),
    'mall': ('daily.mall', None),
    'award': ('daily.award', None),
    'sss': ('periodic.sss', None),
    'training': ('operator.training', None),
}


def daily_steps(modules, prefix='requested'):
    """Compile player module choices, not a second daily business algorithm."""
    from receiver_catalog_v1 import validate
    if not isinstance(modules, list) or not modules:
        raise ValueError('自定义日常modules须为非空数组；不自动补成默认日常')
    result = []
    for index, item in enumerate(modules):
        row = {'task': item} if isinstance(item, str) else item
        if not isinstance(row, dict) or set(row) - {'task', 'inputs', 'enabled'}:
            raise ValueError('日常模块使用任务名或{task,inputs,enabled}')
        if type(row.get('enabled', True)) is not bool:
            raise ValueError('enabled须为true或false')
        name = row.get('task')
        if name not in DAILY_MODULES:
            raise ValueError('该任务不在可组合日常模块中：' + str(name))
        if row.get('enabled', True) is False:
            continue
        params = row.get('inputs', {})
        if not isinstance(params, dict):
            raise ValueError('模块inputs须为JSON对象')
        task, public_goal = DAILY_MODULES[name]
        if public_goal:
            task, params = compile_goal(public_goal, params)
        elif params:
            raise ValueError(name + '当前读取本机MAA/任务配置，不支持临时inputs；不静默忽略参数')
        validate(task, params)
        result.append(dict(key=f'{prefix}_{index + 1}', task=task, inputs=params))
    if not result:
        raise ValueError('没有启用任何日常模块；不自动启动默认日常')
    return result


def goal_steps(task, inputs, prefix='requested'):
    if task == 'daily.custom':
        return daily_steps(inputs['modules'], prefix)
    if task in ('base.infrast', 'daily.final'):
        return [dict(key=prefix + '_base_plan', task='base.prepare'),
                dict(key=prefix, task=task, inputs=inputs, requires=[prefix + '_base_plan'])]
    return [dict(key=prefix, task=task, inputs=inputs)]
