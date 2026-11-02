"""Record AI-reviewed tutorial outcomes; never infer success from a click."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import subprocess
import sys
from event_page_guard_v1 import publish_page_attention
from ark_host.cooperation_v1 import atomic_json


def finish(data, command):
    frames={row['seq']:row for row in data.get('frames',[])}
    if not frames or command.get('seq')!=max(frames) or not command.get('reason'):
        raise ValueError('fresh frame and visual review reason required')
    outcome=command.get('outcome')
    if outcome not in ('passed','human_required'):
        raise ValueError('unsupported tutorial outcome')
    if outcome=='passed':
        if not all(command.get(k) is True for k in (
                'same_stage_verified','completion_marker_verified','returned_to_route_verified')):
            raise ValueError('result and return-route visual review required')
        result_seq=command.get('result_seq')
        route_seq=command.get('route_seq')
        if result_seq not in frames or route_seq not in frames or result_seq>=route_seq:
            raise ValueError('separate result and later route evidence required')
        if route_seq!=max(frames):
            raise ValueError('return route evidence must be current')
        reviewed=[frames[result_seq],frames[route_seq]]
    else:
        if not command.get('unresolved_instruction'):
            raise ValueError('identify the unresolved tutorial step')
        if not data.get('actions') and len(frames)<3:
            raise ValueError('try AI observation before requesting human intervention')
        # Reject a missing-job-only explanation, not a genuine failed visual
        # attempt which happens to mention that no Copilot was available.
        if command['reason'].strip().strip('。.!！') in (
                '没有作业','没有MAA作业','没有 MAA 作业','no_job','automation_unavailable'):
            raise ValueError('missing Copilot alone is not AI failure')
        reviewed=[frames[max(frames)]]
    for frame in reviewed:
        path=Path(frame['path'])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=frame.get('sha256'):
            raise ValueError('tutorial evidence missing or changed')
    data.update(status='ai_visual_pass_verified' if outcome=='passed' else 'needs_user_tutorial',
        outcome_review=dict(command,reviewed_at=datetime.now().astimezone().isoformat()),
        verified_evidence=[r['path'] for r in reviewed],
        automatic_stability_credit=False,whole_daily_complete=False)
    return data


def notify_human(data, output, *, root, spawn=subprocess.Popen):
    """Use the existing plain-language popup without daily completion side effects."""
    if data.get('status')!='needs_user_tutorial':
        return None
    if (data.get('manual_popup') or {}).get('status')=='launched_not_yet_read':
        return data.get('attention_event')
    output=Path(output)
    review=data['outcome_review']
    message=(f"教学关 {data['stage']} 需要你接手\n\n"
        f"AI 已尝试按教学提示操作，但还没能完成这一步：{review['unresolved_instruction']}\n"
        f"原因：{review['reason']}\n\n"
        "请完成这段教学后在对话中说“继续”。这不是整套日常已完成；已完成部分会保留。\n"
        "不依赖该教学关的日常仍由原执行流程处理。")
    path=publish_page_attention(Path(root)/'outputs',data.get('parent_run_id') or data['started_at'],
        data['stage'],'tutorial_ai_needs_human',
        [dict(screenshot=p) for p in data['verified_evidence']])
    packet=json.loads(Path(path).read_text('utf-8'))
    packet.update(status='needs_user_tutorial',requires_user_manual=True,blocks_daily=False,
        affected_scope='tutorial_prerequisite',detail=message,ai_attempt_receipt=str(output/'receipt.json'))
    atomic_json(path,packet)
    data['attention_event']=path
    popup=output/'manual_handoff_popup.json'
    atomic_json(popup,dict(title='明日方舟：教学关需要接手',message=message))
    try:
        process=spawn([sys.executable,str(Path(root)/'show_summary_popup.py'),str(popup)],
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        data['manual_popup']={'status':'launched_not_yet_read','pid':process.pid,'payload':str(popup)}
    except OSError as exc:
        data['manual_popup']={'status':'unavailable','error':str(exc),'payload':str(popup)}
    print('[PROJECT_ATTENTION_NOW] '+json.dumps(dict(path=path,reason='tutorial_ai_needs_human',
        affected_scope='tutorial_prerequisite',blocks_daily=False),ensure_ascii=False),flush=True)
    return path
