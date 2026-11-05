"""Detached lifetime for one selected roguelike invocation, no new scheduler."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ark_host.cooperation_v1 import atomic_json
from ark_host.process_lifetime_v1 import current_job_flags


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--handoff',required=True)
    a=p.parse_args()
    path=(ROOT/a.handoff).resolve();path.relative_to(ROOT/'outputs/continuations')
    packet=json.loads(path.read_text(encoding='utf-8'))
    if packet.get('workflow')!='ARK-SAMI-PROGRESS-V9':raise ValueError('wrong_worker_workflow')
    if datetime.now().astimezone()>=datetime.fromisoformat(packet['deadline']):raise ValueError('worker_deadline_expired')
    output=(ROOT/packet['output']).resolve();output.relative_to(ROOT/'outputs')
    output.mkdir(parents=True,exist_ok=True)
    lifetime=current_job_flags()
    if lifetime and lifetime['kill_on_close']:
        raise RuntimeError('owner_still_in_kill_on_close_job_no_game_started')
    (output/'detached.claim').open('x').close()
    # Actual execution identity is inherited, never changed to impersonate it.
    atomic_json(output/'owner_process.json',dict(pid=os.getpid(),parent_pid=os.getppid(),run_id=packet['run_id'],
        source_thread_id=os.environ.get('CODEX_THREAD_ID'),started_at=datetime.now().astimezone().isoformat(),
        lifetime='detached_from_exec_terminal',windows_job=lifetime,deadline=packet['deadline']))
    sys.stdout=open(output/'stdout.log','a',encoding='utf-8',buffering=1)
    sys.stderr=open(output/'stderr.log','a',encoding='utf-8',buffering=1)
    os.chdir(ROOT)
    sys.argv=[str(ROOT/'run_sami_progress_v9.py'),'--handoff',str(path)]
    code=1
    try:
        runpy.run_path(str(ROOT/'run_sami_progress_v9.py'),run_name='__main__')
        code=0
    except SystemExit as exc:
        code=exc.code if isinstance(exc.code,int) else 1
    except BaseException:
        import traceback
        traceback.print_exc()
    finally:
        atomic_json(output/'owner_exit.json',dict(run_id=packet['run_id'],exit_code=code,
            finished_at=datetime.now().astimezone().isoformat()))
    return code


if __name__=='__main__':raise SystemExit(main())
