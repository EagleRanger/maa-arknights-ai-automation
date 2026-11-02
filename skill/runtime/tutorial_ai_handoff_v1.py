"""Route a tutorial capability gap to AI, not a blanket human-only verdict."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
import json
from event_page_guard_v1 import publish_page_attention

@contextmanager
def boundary(app):
    old_record=app._record_event_manual_prerequisite
    old_block=app._block_stamina_flow
    def record(event,target,stage,evidence_path=None):
        row=old_record(event,target,stage,evidence_path=evidence_path)
        reason=f'{stage}教学关待AI按实图尝试；完成后继续{target}'
        row.update(status='needs_ai_tutorial',requires_user_manual=False,reason=reason,
                   next_action='exact_job_lookup_then_AI_visible_instruction_test_at_idle_boundary')
        key=app._RUN_SUMMARY.setdefault('navigation_guard_run_key',datetime.now().astimezone().isoformat())
        path=publish_page_attention(app.OUTPUT_DIR,key,stage,'tutorial_needs_ai',
            [dict(screenshot=evidence_path)] if evidence_path else [])
        packet=json.loads(Path(path).read_text('utf-8'))
        packet.update(affected_scope='tutorial_prerequisite',blocks_daily=False,
            requested_action=row['next_action'],requires_user_manual=False,
            target_stage=target,detail=reason)
        Path(path).write_text(json.dumps(packet,ensure_ascii=False,indent=2),encoding='utf-8')
        row['attention_event']=path
        print('[PROJECT_ATTENTION_NOW] '+json.dumps(dict(path=path,reason='tutorial_needs_ai',
            affected_scope='tutorial_prerequisite',blocks_daily=False),ensure_ascii=False),flush=True)
        return row
    def block(reason,source=None,**kwargs):
        if source=='event_manual_prerequisite':
            row=(app._RUN_SUMMARY.get('event') or {}).get('manual_prerequisite') or {}
            if row.get('status')=='needs_ai_tutorial':
                reason=row['reason']
                app._RUN_SUMMARY.setdefault('flow_control',{})['reason']=reason
        return old_block(reason,source=source,**kwargs)
    with patch.object(app,'_record_event_manual_prerequisite',record), \
         patch.object(app,'_block_stamina_flow',block):yield
