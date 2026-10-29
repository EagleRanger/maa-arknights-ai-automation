"""Recognize both single and native batch MAA Fight consumption boundaries."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import re
from unittest.mock import patch

ACTION=re.compile(r'开始行动\s*(\d+)(?:\s*[~～–-]\s*(\d+))?\s*次\s*[,，]\s*[-−](\d+)\s*理智')
STAMP=re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')


def latest_fight(text,now=None):
    now=now or datetime.now()
    day=lambda t:(t-timedelta(hours=4)).date()
    active=False;spent=False;latest=None
    for line in (text or '').splitlines():
        if '开始任务: 理智作战' in line or 'Start Task Chain: Fight' in line:
            if not active:active=True;spent=False
            continue
        match=ACTION.search(line) if active else None
        if match:
            first=int(match[1]);last=int(match[2] or match[1]);cost=int(match[3])
            spent=spent or (0<first<=last and cost>0)
        if active and ('完成任务: 理智作战' in line or 'Completed Task Chain: Fight' in line):
            active=False;stamp=STAMP.search(line)
            if spent and stamp:
                at=datetime.fromisoformat(stamp[1])
                if at<=now and day(at)==day(now):latest=max(latest,at) if latest else at
    return latest


@contextmanager
def boundary(app):
    with patch.object(app,'_latest_completed_fight_at_from_gui_log',latest_fight):
        yield
