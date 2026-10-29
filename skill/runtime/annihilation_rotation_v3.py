"""V2 navigation plus current-attempt brief recognition and consumed-job guard."""
from datetime import datetime
from pathlib import Path
import re
import annihilation_rotation_v2 as previous
from annihilation_brief_v1 import verify


def progress_panel(rows, stage, evidence, binding_evidence):
    """Read the 400-kill row, not the 7/8 milestone or another reward row."""
    labels=[(x,y) for text,x,y in rows if
            re.fullmatch(r'单次作战达到400(?:歼灭数|击杀数|歼敌数)',previous.v1.compact(text))]
    if len(labels)!=1 or not binding_evidence:
        return None
    x,y=labels[0]
    values=set()
    for text,tx,ty in rows:
        match=re.fullmatch(r'(\d{1,3})/400',previous.v1.compact(text))
        if match and tx>1200 and abs(ty-y)<70 and 0<=int(match[1])<=400:
            values.add(int(match[1]))
    if len(values)!=1:
        return None
    kills=values.pop()
    return dict(status='complete' if kills==400 else 'first_clear_required',
                map=stage,kills=kills,evidence=evidence,map_binding_evidence=binding_evidence,
                reason='exact_400_kill_reward_row')


class RuntimePort(previous.RuntimePort):
    def _observe(self,items,maps,evidence):
        result=super()._observe(items,maps,evidence)
        brief=self.app._RUN_SUMMARY.get('annihilation_rotation',{}).get('battle_brief',{})
        # The current attempt's two-frame 400 brief plus this exact map's
        # final milestone are joint proof even after its reward was claimed.
        if (result.get('map',{}).get('stage_id')==brief.get('stage_id')
                and result.get('progress')=={'value':8,'max':8}
                and brief.get('status')=='full_kills' and brief.get('kills')==400
                and brief.get('verification')=='two_current_frames'
                and brief.get('dismissal')=='verified'):
            result.update(status='complete',kills=400,reason='current_400_brief_and_exact_map_final_milestone',
                          brief_evidence=brief['evidence'])
        return result

    def inspect(self):
        self._detail_ready=None
        result=super().inspect()
        if result.get('reason')!='progress_panel_400_unverified' or not self.idle():
            return result
        stage=result['map'];binding=result['detail_evidence']
        path,rows=self.frame('progress_exact')
        first=progress_panel(rows,stage,path,binding)
        if first is None:
            return result
        self.app.wait(1)
        confirm,items=self.frame('progress_exact_confirm')
        second=progress_panel(items,stage,confirm,binding)
        if not second or not previous.v1.agree(first,second) or not self.idle():
            return dict(result,reason='progress_exact_frames_disagree')
        # Reuse the already verified reward-list exit; only once, not a loop.
        self.app.back();self.app.wait(2)
        detail,items=self.frame('progress_exact_closed')
        text=previous.v1.compact(' '.join(r[0] for r in items))
        if stage['name'] not in text or '开始行动' not in text or '单次作战达到' in text:
            return dict(result,reason='progress_exact_return_unverified',evidence=detail)
        second['after_detail_evidence']=detail
        second['before_evidence']=path
        self._detail_ready=second
        return second

    def enter_formation(self,stage):
        known=getattr(self,'_detail_ready',None)
        self._detail_ready=None
        if not known:
            return super().enter_formation(stage)
        if known['status']!='first_clear_required' or known['map']['stage_id']!=stage['stage_id'] or not self.idle():
            return False
        path,items=self.frame('exact_before_formation')
        text=previous.v1.compact(' '.join(r[0] for r in items))
        target=previous.v1.unique_button(items,'开始行动')
        if stage['name'] not in text or not target or '单次作战达到' in text:
            return False
        self.app.tap(*target);self.app.wait(2)
        path,items=self.frame('exact_formation')
        return self.app._is_formation_page_text(' '.join(r[0] for r in items)) is True

    def consumed(self, stage, job):
        handoff = previous.read(Path(self.app.BASE)/'.project-reasoning/AUTOMATION_HANDOFF.json')
        rows = (handoff.get('current_weekly_annihilation_intake') or {}).get('consumed_job_attempts', [])
        return any(r.get('stage_id') == stage['stage_id'] and
                   str(r.get('sha256', '')).lower() == str(job.get('sha256', '')).lower()
                   for r in rows)

    def approved_job(self, stage):
        job = super().approved_job(stage)
        return None if job and self.consumed(stage, job) else job

    def battle(self, job, stage):
        if self.consumed(stage, job):
            return 'reviewed_attempt_already_consumed'
        started_at = datetime.now().astimezone()
        if not self.app.run_maa_copilot(job['path']):
            return 'start_failed'
        return verify(self, stage, started_at)
