"""Bounded UIA queue-start worker. Parent alone monitors MAA and owns game.

No thread timeout can cancel a blocked COM provider; only this short-lived
worker process is terminated. MAA/game are never terminated by this adapter.
"""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import json
import os
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
ALLOWED = {'StartUp','Infrast','Recruit','Mall','Award','Fight','Depot','UserDataUpdate'}

class QueueStartUnverified(BaseException):
    """Uncertain commit: bypass generic business retries and preserve scene."""

def worker_command(path):
    # Windows venv python.exe is a redirector and adds an intermediate process.
    # Use its matching real interpreter with this validated runtime's imports;
    # the Popen PID is then the actual cancellable UIA process, not a launcher.
    code=('import sys,runpy; sys.path[:0]='+repr(sys.path)+'; '
          'sys.argv=['+repr(str(Path(__file__)))+','+repr(str(path))+']; '
          'runpy.run_path(sys.argv[0],run_name="__main__")')
    return [getattr(sys,'_base_executable',sys.executable),'-X','utf8','-c',code]


def classify(returncode, receipt, text, enabled, timed_out=False):
    if returncode == 0 and receipt.get('started') is True and not timed_out:
        return 'started'
    # Fresh callback proves a queue was sent even if Invoke never returned.
    if any('TaskChainStart' in line and any('"taskchain":"'+c+'"' in line for c in enabled)
           for line in text.splitlines()):
        return 'started_callback'
    if returncode == 0 and receipt.get('started') is False and not timed_out:
        return 'not_started'
    return 'unknown'


@contextmanager
def boundary(app, *, timeout=120, process_factory=subprocess.Popen):
    uncertain = [False]
    original_state = app._maa_task_queue_running
    original_cleanup = getattr(app,'cleanup_after_task',None)
    def cleanup(*a,**k):
        if uncertain[0]:
            app._RUN_SUMMARY['queue_cleanup_deferred']=True
            app.log('[MAA有界启动] 提交结果未知，保留现场等待对账，不杀MAA/游戏')
            return False
        return original_cleanup(*a,**k) if original_cleanup else None
    def queue_state():
        # Unknown submission must not be interpreted as idle and reconfigured.
        return True if uncertain[0] else original_state()
    def start(enabled_tasks=None):
        if uncertain[0] or original_state() is not False:
            return False
        enabled = set(enabled_tasks or {'StartUp','Infrast','Recruit','Mall','Award'})
        if not enabled or not enabled <= ALLOWED:
            raise ValueError('unsupported named queue')
        # Lifecycle/config remain in the owning parent. No MAA process may be
        # a child of a worker that can be terminated on a UIA timeout.
        config=Path(app.MAA_CONFIG)/'gui.new.json'
        cfg=json.loads(config.read_text(encoding='utf-8'))
        before=[(t.get('TaskType'),t.get('IsEnable')) for t in app._task_queue(cfg)]
        app._set_enabled_tasks(cfg,enabled)
        after=[(t.get('TaskType'),t.get('IsEnable')) for t in app._task_queue(cfg)]
        if before!=after:
            app._atomic_write_json(str(config),cfg)
            if app._maa_process_exists():app.reload_maa_after_config_switch('bounded queue parent configuration')
        if not app._maa_process_exists():app._launch_maa_for_background_control()
        out = ROOT/'outputs/maa_queue_workers'/uuid.uuid4().hex
        out.mkdir(parents=True)
        request = dict(parent_pid=os.getpid(), enabled=sorted(enabled), output=str(out),
                       portable_root=str(Path(app.MAA_PATH).parent))
        (out/'request.json').write_text(json.dumps(request),encoding='utf-8')
        # Preserve the parent's run-start time; only set this queue's log offset.
        try:
            with open(app.MAA_LOG,encoding='utf-8',errors='replace') as stream:
                app._LAST_MAA_RUN_START_LINE = sum(1 for _ in stream)
        except OSError:
            app._LAST_MAA_RUN_START_LINE = 0
        app._LAST_MAA_RUN_LOG = ''; app._LAST_MAA_RUN_SEGMENT = ''
        kwargs = dict(cwd=ROOT, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        timed_out = False
        with (out/'worker.log').open('w',encoding='utf-8') as log:
            p = process_factory(worker_command(out/'request.json'),
                                stdout=log,stderr=subprocess.STDOUT,**kwargs)
            try:
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out=True; p.kill(); p.wait(timeout=10)
        receipt_path=out/'worker_result.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {}
        text=app._get_current_maa_run_log()
        state=classify(p.returncode,receipt,text,enabled,timed_out)
        row=dict(status=state,timed_out=timed_out,worker_exit=p.returncode,
                 enabled=sorted(enabled),evidence=str(out),at=datetime.now().astimezone().isoformat())
        (out/'parent_result.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
        app._RUN_SUMMARY.setdefault('queue_start_workers',[]).append(row)
        app.log('[MAA有界启动] '+state+'; '+str(out))
        if state=='unknown':
            uncertain[0]=True
            app._RUN_SUMMARY['page_attention']=dict(reason='queue_start_unverified',evidence=str(out))
            raise QueueStartUnverified('UIA worker ended without queue-start proof: '+str(out))
        return state in ('started','started_callback')
    with patch.object(app,'run_maa_daily_tasks',start),patch.object(app,'_maa_task_queue_running',queue_state), \
         patch.object(app,'cleanup_after_task',cleanup,create=True):
        yield


def worker(path):
    path=Path(path).resolve(); path.relative_to(ROOT/'outputs/maa_queue_workers')
    req=json.loads(path.read_text(encoding='utf-8'))
    if req['parent_pid']!=os.getppid() or not set(req['enabled']) <= ALLOWED or not req['enabled']:
        raise ValueError('worker must belong to the live parent and named queue')
    out=Path(req['output']).resolve()
    if out!=path.parent: raise ValueError('worker output mismatch')
    if req.get('probe_only'):
        import uiautomation
        import arknights_daily_runtime_v12
        (out/'worker_result.json').write_text(json.dumps({'parent_verified':True,
            'pid':os.getpid(),'parent_pid':os.getppid(),'imports_ready':True,'game_actions':0}),encoding='utf-8')
        if req.get('probe_delay'):
            import time
            time.sleep(min(10,max(0,float(req['probe_delay']))))
        return
    from maa_portable_runtime_v1 import bind, PORTABLE_ROOT
    if Path(req['portable_root']).resolve()!=PORTABLE_ROOT.resolve():
        raise ValueError('portable MAA identity mismatch')
    import arknights_daily_runtime_v12 as app
    bind(app)
    # No environment boot, mutex ownership, full/daily main or cleanup here.
    def no_reload(*a,**k):raise RuntimeError('parent must prepare configuration before UIA')
    with patch.object(app,'_launch_maa_for_background_control',lambda:None), \
         patch.object(app,'reload_maa_after_config_switch',no_reload), \
         patch.object(app,'_finalize_maa_update_before_control',lambda ua,maa,**kw:maa):
        started=app.run_maa_daily_tasks(enabled_tasks=set(req['enabled'])) is True
    (out/'worker_result.json').write_text(json.dumps({'started':started}),encoding='utf-8')


if __name__=='__main__': worker(sys.argv[1])
