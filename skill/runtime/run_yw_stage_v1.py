"""Bounded YW candidate trial; reuse existing navigation/Copilot/result loop.

Not a replacement daily scheduler. Execution owns the live game and invokes
this only for the stages in the project's current YW trial handoff.
"""
from datetime import datetime
from pathlib import Path
import argparse
import json
import subprocess
import sys
from contextlib import contextmanager

ROOT=Path(__file__).resolve().parent
MANIFEST=ROOT/'outputs/yw_20261009/admitted_candidates/candidate_manifest.json'
HANDOFF=ROOT/'outputs/yw_20261009/live_trial_handoff.json'

def yw_badge_ratio(image_path):
    """YW detail: each of the three observed hexagons must be cyan-lit.

    Geometry observed in the 2026-10-09 YW-1 detail, not the SR-EX layout.
    Returning the minimum prevents two bright badges from hiding one dark one.
    """
    from PIL import Image
    with Image.open(image_path) as original:
        im=original.convert('RGB');w,h=im.size
        ratios=[]
        for cx in (0.816,0.861,0.906):
            pixels=list(im.crop((int(w*(cx-.020)),int(h*.127),
                                 int(w*(cx+.020)),int(h*.197))).getdata())
            ratios.append(sum(b>150 and g>100 and b>r*1.3 for r,g,b in pixels)/len(pixels))
    return min(ratios)

def admission(code, now=None):
    from vector_special_resources_v1 import verified_candidates
    h=json.loads(HANDOFF.read_text(encoding='utf-8'))
    now=now or datetime.now().astimezone()
    if h.get('status')!='READY' or code not in h.get('allowed_stages',[]):
        raise ValueError('No current candidate trial for this stage')
    if now>=datetime.fromisoformat(h['deadline']):
        raise ValueError('Current trial run deadline passed')
    rows=verified_candidates(ROOT,MANIFEST)
    row=next(r for r,*_ in rows if r['code']==code)
    if h.get('resources')!='existing_sanity_only_no_refills':
        raise ValueError('Unexpected resource boundary')
    return h,row

@contextmanager
def candidate_jobs(a, row, deadline=None):
    from vector_copilot_requirements_v1 import engine_boundary
    old=a.get_copilot_json
    path=ROOT/row['job_path']
    def source(internal,display,attempt=0,excluded_paths=None,**kwargs):
        if deadline is not None and datetime.now().astimezone()>=datetime.fromisoformat(deadline):
            raise RuntimeError('YW trial deadline reached before loading battle job')
        if internal!=row['internal_stage'] or display!=row['code']:
            raise ValueError('Candidate job requested for a different stage')
        if path.name in {Path(p).name for p in excluded_paths or []}:
            return None  # Never repeat this failed source unchanged.
        return str(path)
    a.get_copilot_json=source
    try:
        with engine_boundary(a,ROOT/'outputs/yw_20261009/trials'):
            yield
    finally:
        a.get_copilot_json=old

def run(code):
    h,row=admission(code)
    from vector_special_runtime_v1 import runtime
    from vector_special_resources_v1 import install
    a=runtime()
    if not a.acquire_single_instance():
        raise RuntimeError('Game controller already owned')
    try:
        if a._maa_task_queue_running() is not False:
            raise RuntimeError('Existing queue must reach its boundary first')
        manifest=json.loads(MANIFEST.read_text(encoding='utf-8'))
        event=manifest['event']
        # Recheck the real battle-open interval, not the later reward-shop end.
        from yw_event_intake_v1 import event_config,SOURCE
        event_config(json.loads((SOURCE/'catalog.json').read_text(encoding='utf-8')))
        a.ACTIVE_EVENTS.insert(0,event)
        a._DAILY_EXISTING_SANITY_ONLY=True
        a._event_normal_badges_ratio=yw_badge_ratio
        resources=install(ROOT,a.MAA_ROOT,MANIFEST,queue_idle=lambda:a._maa_task_queue_running() is False)
        if resources.get('changed') and a._maa_process_exists():
            a.reload_maa_after_config_switch('YW地图资源候选已核验，空闲重载')
        if not a.ensure_env():
            raise RuntimeError('YW environment not ready; no battle started')
        stage=next(s for s in event['stages'] if s['display']==code)
        result={'stage':code,'started_at':datetime.now().astimezone().isoformat(),
                'job_id':row['job_id'],'resource_install':resources,'game_clear_verified':False,
                'resource_boundary':h['resources'],'daily_complete':False}
        before=a.shot(code+'_trial_before')
        result['before']=before
        result['before_ocr']=a.ocr_text(before)
        # Existing detail -> formation -> MAA -> settlement -> live badges loop.
        # Its persistent stage budget and no-refill behavior are retained.
        with candidate_jobs(a,row,h['deadline']):
            outcome=a.clear_event_stage(event,stage,mode='normal',max_attempts=5)
        after=a.shot(code+'_trial_after')
        result.update(outcome=str(outcome),after=after,after_ocr=a.ocr_text(after),
                      game_clear_verified=outcome is True,
                      finished_at=datetime.now().astimezone().isoformat())
        output=ROOT/'outputs/yw_20261009/stage_receipts'/f'{code}_latest.json'
        a._atomic_write_json(str(output),result)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if outcome is True else 2
    finally:
        a.release_single_instance()

if __name__=='__main__':
    from run_daily_v78 import PYTHON
    if Path(sys.executable).resolve()!=PYTHON.resolve():
        raise SystemExit(subprocess.run([str(PYTHON),'-X','utf8','-u',str(Path(__file__).resolve()),
                                         *sys.argv[1:]],cwd=ROOT).returncode)
    from run_daily_v19 import _runtime_probe
    if not _runtime_probe()['symbols_ready']:
        raise RuntimeError('Verified interpreter is missing its OCR/UI dependencies; no game action')
    p=argparse.ArgumentParser();p.add_argument('--stage',required=True)
    raise SystemExit(run(p.parse_args().stage))
