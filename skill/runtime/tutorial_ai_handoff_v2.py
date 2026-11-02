"""Tutorials: existing compatible job, AI visual attempt, then human fallback."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import json
import re
from event_page_guard_v1 import publish_page_attention
from ark_host.cooperation_v1 import atomic_json

GUIDE = [
    '已有精确兼容MAA作业可直接复用；无作业不等于需用户手动，不反复等待搜索。',
    '先交原AI对话；MAA空闲且原控制者交回后，用现有后台截图/输入接管这个教学步骤。',
    '读当前教学文字、手势和高亮格，确认要求的干员或装置、落点和朝向。',
    '选择卡片后重截：视角可能倾斜，禁止沿用选择前的格子坐标。',
    '部署、朝向分开观察；用费用/卡片数量/场上单位/教学文字变化确认动作生效。',
    '无变化先新图纠正，同一指令连续三次仍无进展才转人工；不是整关只许三个动作。',
    '同关结算与地图/详情完成证据核验后回原后续目标；不凭MAA结束或点击次数报通关。',
    'AI无法完成才弹教学关转人工提示，保留截图和未解决步骤；不扩大药石/关卡范围。',
]


def is_tutorial(event, stage):
    if re.fullmatch(r'(?:[A-Z0-9]+-)?TR-\d+',str(stage).upper()):
        return True
    return any(row.get('display')==stage and row.get('kind','tutorial')=='tutorial'
               for row in (event or {}).get('tutorial_stages',[]))


@contextmanager
def boundary(app):
    old_record=app._record_event_manual_prerequisite
    old_block=app._block_stamina_flow
    old_log=app.log
    old_clear=app.clear_event_stage
    def record(event,target,stage,evidence_path=None):
        row=old_record(event,target,stage,evidence_path=evidence_path)
        if not is_tutorial(event,stage):
            return row
        reason=f'{stage}教学关先由AI按画面提示尝试；仍无法通过才转人工，完成后继续{target}'
        row.update(status='needs_ai_tutorial',requires_user_manual=False,reason=reason,
                   next_action='ai_visual_tutorial_attempt',guide=GUIDE,
                   session_entry='tools/tutorial_session_v2.py',
                   documentation='docs/tutorial_ai_v2.md')
        app._RUN_SUMMARY.setdefault('event',{}).setdefault('stages',{}).setdefault(target,{}).update(
            status='needs_ai_tutorial',detail=reason)
        key=app._RUN_SUMMARY.setdefault('navigation_guard_run_key',datetime.now().astimezone().isoformat())
        path=publish_page_attention(app.OUTPUT_DIR,key,stage,'tutorial_needs_ai',
            [dict(screenshot=evidence_path)] if evidence_path else [])
        packet=json.loads(Path(path).read_text('utf-8'))
        packet.update(affected_scope='tutorial_prerequisite',blocks_daily=False,
            requested_action='ai_visual_tutorial_attempt',requires_user_manual=False,
            target_stage=target,detail=reason,guide=GUIDE,
            session_entry=row['session_entry'],documentation=row['documentation'])
        atomic_json(path,packet)
        row['attention_event']=path
        print('[PROJECT_ATTENTION_NOW] '+json.dumps(dict(path=path,reason='tutorial_needs_ai',
            affected_scope='tutorial_prerequisite',blocks_daily=False),ensure_ascii=False),flush=True)
        return row
    def block(reason,source=None,**kwargs):
        row=(app._RUN_SUMMARY.get('event') or {}).get('manual_prerequisite') or {}
        if source=='event_manual_prerequisite' and row.get('status')=='needs_ai_tutorial':
            reason=row['reason']
            app._RUN_SUMMARY.setdefault('flow_control',{})['reason']=reason
        return old_block(reason,source=source,**kwargs)
    def log(message,*args,**kwargs):
        row=(app._RUN_SUMMARY.get('event') or {}).get('manual_prerequisite') or {}
        if (row.get('status')=='needs_ai_tutorial' and row.get('prerequisite','?') in str(message)
                and '教学关' in str(message) and '手动完成' in str(message)):
            message=row['reason']+'；仅等待控制权安全交接，不要求用户重复授权。'
        return old_log(message,*args,**kwargs)
    def clear(event,stage,*args,**kwargs):
        result=old_clear(event,stage,*args,**kwargs)
        name=stage.get('display')
        if result in ('no_job','automation_unavailable') and is_tutorial(event,name):
            record(event,'后续活动关',name)
            return ('manual_required',name)  # Existing coordinator return shape.
        return result
    with patch.object(app,'_record_event_manual_prerequisite',record), \
         patch.object(app,'_block_stamina_flow',block),patch.object(app,'log',log), \
         patch.object(app,'clear_event_stage',clear):
        yield
