"""Resource restrictions on an active receiver continuation; no device I/O."""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
LOCAL=timezone(timedelta(hours=8))

def current_intent(root, now=None):
    """Use the existing handoff, not a second task/authorization database."""
    path = Path(root)/'.project-reasoning/AUTOMATION_HANDOFF.json'
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    scope = data.get('current_daily_continuation') or {}
    now = now or datetime.now(LOCAL)
    day = (now.astimezone(LOCAL)-timedelta(hours=4)).date().isoformat()
    if scope.get('status') == 'active' and scope.get('game_day') == day:
        return scope
    return {}


def farm_restriction(event, scope, now=None):
    if scope.get('allow_event_farm') is False:
        return '用户当前指定任务优先，现有理智不用于材料补刷'
    now = now or datetime.now(LOCAL)
    for section in (event or {}).get('pending_sections', []):
        when = section.get('opens_at')
        if when and datetime.fromisoformat(when) <= now:
            return '活动已到新阶段开放时间，尚未接入任务列表：' + str(section.get('name', '新阶段'))
    return None
