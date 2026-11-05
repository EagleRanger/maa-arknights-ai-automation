"""V1 hidden owner using the real interpreter, not Windows venv redirector."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ark_host.cooperation_v1 import read_message,atomic_json


def worker_command(handoff):
    worker=ROOT/'tools/owned_roguelike_worker_v2.py'
    code=('import sys,runpy;sys.path[:0]='+repr(sys.path)+';sys.argv=['+
        repr(str(worker))+',\'--handoff\','+repr(str(handoff))+'];'+
        'runpy.run_path(sys.argv[0],run_name=\'__main__\')')
    return [sys._base_executable,'-X','utf8','-c',code]


def main():
    p=argparse.ArgumentParser();p.add_argument('--handoff',required=True);p.add_argument('--check-only',action='store_true')
    a=p.parse_args();path=(ROOT/a.handoff).resolve();path.relative_to(ROOT/'outputs/continuations')
    packet=read_message(path)
    output=(ROOT/packet['output']).resolve()
    output.relative_to((ROOT/'outputs').resolve())
    from maa_portable_runtime_v1 import preflight
    preflight(write_probe=False)
    check=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'run_sami_progress_v9.py'),
        '--handoff',str(path),'--check-only'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    if check.returncode:raise RuntimeError(check.stderr or check.stdout)
    if a.check_only:print(check.stdout.strip());return 0
    output.mkdir(parents=True,exist_ok=True)
    if (output/'detached.claim').exists() or (output/'host.claim').exists():raise ValueError('existing_run_not_replayed')
    with (output/'bootstrap_stdout.log').open('a',encoding='utf-8') as stdout, \
         (output/'bootstrap_stderr.log').open('a',encoding='utf-8') as stderr:
        child=subprocess.Popen(worker_command(path),cwd=ROOT,stdin=subprocess.DEVNULL,
            stdout=stdout,stderr=stderr,close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP|0x01000000)
    for _ in range(40):
        owner=read_message(output/'owner_process.json')
        if owner.get('run_id')==packet['run_id']:
            receipt=dict(status='owner_started',pid=owner['pid'],launcher_child_pid=child.pid,
                run_id=packet['run_id'],output=str(output),job_breakaway_requested=True,
                interpreter='real_interpreter_with_original_import_paths',windows_job=owner.get('windows_job'))
            atomic_json(output/'launch_receipt.json',receipt)
            print(json.dumps(receipt,ensure_ascii=False));return 0
        if child.poll() is not None:
            error=(output/'bootstrap_stderr.log').read_text(encoding='utf-8',errors='replace')[-2500:]
            atomic_json(output/'launch_error.json',dict(exit_code=child.returncode,error=error))
            raise RuntimeError('owner_exited_before_receipt:'+str(child.returncode)+' '+error)
        time.sleep(.2)
    raise RuntimeError('owner_receipt_unknown_do_not_replay')


if __name__=='__main__':raise SystemExit(main())
