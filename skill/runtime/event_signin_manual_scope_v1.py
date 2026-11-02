"""Honor same-day user-completed sign-in without replaying its navigation."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import json
from event_signin_discovery_v6 import game_day
from daily_home_state_v1 import home_anchors

ROOT=Path(__file__).resolve().parent

def applicable(fact,target,day):
    return (fact.get('status')=='user_completed' and fact.get('game_day')==day
            and fact.get('scope')=='activity_signin_only' and bool(fact.get('source_user_text'))
            and str(fact.get('created_timestamp'))==str(target.get('created_timestamp'))
            and fact.get('package')==target.get('package'))

@contextmanager
def boundary():
    import event_signin_lifecycle_v1 as lifecycle
    old_service,old_lines=lifecycle.service,lifecycle.report_lines
    def service(app,**kwargs):
        handoff=json.loads((ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json').read_text(encoding='utf-8'))
        fact=(handoff.get('daily_runtime') or {}).get('manual_signin_completion') or {}
        target=app._RUN_SUMMARY.get('game_runtime_target') or {}
        day=kwargs.get('day') or game_day()
        if not applicable(fact,target,day):return old_service(app,**kwargs)
        p=str(app.shot('manual_signin_completed_home_check'));rows=app.ocr(p)
        text=' '.join(str(t) for t,x,y in rows)
        from event_signin_generic_v2 import ticket_offer
        from event_celebration_login_v1 import is_celebration_calendar
        if not home_anchors(rows) or ticket_offer(text) or is_celebration_calendar(text):
            return old_service(app,**kwargs)  # User fact never fakes navigation.
        return dict(component='ARK-SIGNIN-MANUAL-SCOPE-V1',game_day=day,status='checked',
            home_verified=True,claimed_count=0,entries=[],activities=[],evidence=[p],
            reason='user_completed_today_skip_signin_navigation',manual_completed=True,
            automatic_claim_verified=False,source_user_text=fact['source_user_text'],
            blocking_scope='none',continue_daily=True)
    def lines(report):
        result=old_lines(report)
        rows=(report.get('run_summary') or {}).get('event_signin_discovery') or []
        if any(r.get('manual_completed') for r in rows):
            result.append('活动签到：你已手动完成今日领奖，本轮不重复进入；不计作自动领取。')
        return result
    with patch.object(lifecycle,'service',service),patch.object(lifecycle,'report_lines',lines):yield
