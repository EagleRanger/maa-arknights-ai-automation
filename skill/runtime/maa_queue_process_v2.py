"""V1 process isolation plus native-filtered discovery and hang stack evidence."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import faulthandler
import json
import sys

import maa_queue_process_v1 as previous
from maa_window_handle_v2 import find

_BASE_BOUNDARY=previous.boundary


def worker_command(path):
    code=('import sys,runpy; sys.path[:0]='+repr(sys.path)+'; '
          'sys.argv=['+repr(str(Path(__file__)))+','+repr(str(path))+']; '
          'runpy.run_path(sys.argv[0],run_name="__main__")')
    return [getattr(sys,'_base_executable',sys.executable),'-X','utf8','-c',code]


@contextmanager
def boundary(app,**kwargs):
    def command(path):
        req=json.loads(Path(path).read_text(encoding='utf-8'))
        req['device']=getattr(app,'DEVICE',None)
        Path(path).write_text(json.dumps(req),encoding='utf-8')
        return worker_command(path)
    with patch.object(previous,'worker_command',command), \
         patch.object(app,'_find_real_maa_window',lambda ua:find(ua,app.MAA_PATH),create=True), \
         _BASE_BOUNDARY(app,**kwargs):
        yield


def worker(path):
    path=Path(path).resolve();path.relative_to(previous.ROOT/'outputs/maa_queue_workers')
    req=json.loads(path.read_text(encoding='utf-8'));out=path.parent
    def trace(**row):
        with (out/'phases.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    with (out/'stack.txt').open('w',encoding='utf-8') as stack:
        faulthandler.enable(file=stack)
        faulthandler.dump_traceback_later(30,repeat=True,file=stack)
        try:
            import arknights_daily_runtime_v12 as app
            if req.get('device'):app.DEVICE=req['device']
            trace(phase='worker_enter',device=getattr(app,'DEVICE',None))
            with patch.object(app,'_find_real_maa_window',lambda ua:find(ua,app.MAA_PATH,trace)):
                previous.worker(path)
            trace(phase='worker_returned')
        except BaseException as exc:
            trace(phase='worker_error',error=repr(exc));raise
        finally:
            faulthandler.cancel_dump_traceback_later()


if __name__=='__main__':worker(sys.argv[1])
