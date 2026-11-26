"""Opt-in single-owner trial. A native return is never proof of a badge."""
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def params(inputs,limit=5):
    if set(inputs)-{'target','runs','attempts'}:raise ValueError('不支持的刷角标参数')
    t,r,a=(inputs.get(k,v) for k,v in [('target',3),('runs',1),('attempts',1)])
    if (any(type(n) is not int for n in (t,r,a)) or t not in (3,6)
            or not 1<=r<=a<=limit):raise ValueError('角标等级须为3或6；胜场和尝试须为正整数，不超本机预算')
    return dict(mode='badge',theme='Regulation',target=t,runs=r,attempts=a)


def run(session,inputs,context,previous,operation):
    from ark_modules.core import Result
    from maa_utility_custom_v1 import _submit
    app=session.app
    task=params(inputs,getattr(app,'_PUBLIC_TASK_MAX_ATTEMPTS',5))
    if not session.queue_idle():return Result('blocked','原队列仍在运行')
    res=Path(app._maa_install_root())/'resource/tasks/StrongholdProtocol/StrongholdProtocol.json'
    if not res.is_file():return Result('blocked','本机 MAA 尚无新版卫戍协议资源')
    before=str(app.shot('stronghold_badge_before'))
    words=''.join(str(t).replace(' ','') for t,_,_ in app.ocr(before))
    if (not all(k in words for k in ('规程','极速模拟','功勋兑换处'))
            or any(k in words for k in ('继续模拟','放弃','确认退出','结算奖励'))):
        return Result('partial','先由原执行者确认默认皮肤、无未完存档并进入规程的极速模拟活动主页；未提交',
                      (before,))
    deadline=datetime.fromisoformat(context.deadline)
    remaining=int((deadline-datetime.now(deadline.tzinfo)).total_seconds())
    if remaining<30:return Result('blocked','专项已到截止边界')
    out=Path(session.output)/('stronghold_badge_'+uuid4().hex)
    result=_submit(app,'StrongholdProtocol',task,'stronghold_badges',out,timeout=min(3600,remaining))
    after=str(app.shot('stronghold_badge_after'))
    return Result('partial','卫戍角标待实图核对；原生任务结束不等于角标增加',
                  (before,after,str(out/'callbacks.json')),dict(native=result,params=task,badge_change_verified=False))
