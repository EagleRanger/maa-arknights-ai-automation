"""Plan current, visually proved SSS objectives without equating caps to clears."""
import re


def pending_regions(audit, visible_regions):
    pending=[]
    for name in visible_regions:
        records=(audit.get('records') or {}).get(name) or {}
        unmet=any(r.get('state')=='incomplete' for r in records.get('rows',{}).values())
        for card in (audit.get('tasks') or {}).get('cards',[]):
            text=re.sub(r'\s+','',card.get('title',''))
            if card.get('state')=='incomplete' and text=='通关'+name:
                unmet=True
        if unmet:
            pending.append(name)
    return pending


def work_plan(audit, visible_regions, supported_formations, has_job):
    """Only established formations auto-run; new regions need precise validation."""
    rows=[]
    for name in pending_regions(audit,visible_regions):
        job=has_job(name)
        reason=('matching_job_missing' if not job else
                'formation_not_validated' if name not in supported_formations else None)
        rows.append({'region':name,'action':'deferred' if reason else 'clear_then_reaudit',
                     'reason':reason,'evidence_source':'current_tasks_and_six_stage_records'})
    return rows
