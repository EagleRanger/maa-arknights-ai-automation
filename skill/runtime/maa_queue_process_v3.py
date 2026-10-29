"""Keep the accepted isolated submitter, with foreground calls disabled in both processes."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import sys
import maa_queue_process_v2 as previous

_BOUNDARY=previous.boundary


def worker_command(path):
    code=('import sys,runpy; sys.path[:0]='+repr(sys.path)+'; '
          'sys.argv=['+repr(str(Path(__file__)))+','+repr(str(path))+']; '
          'runpy.run_path(sys.argv[0],run_name="__main__")')
    return [getattr(sys,'_base_executable',sys.executable),'-X','utf8','-c',code]


@contextmanager
def boundary(app,**kwargs):
    with patch.object(previous,'worker_command',worker_command), \
         patch.object(app,'_foreground_mumu_display',lambda:True),_BOUNDARY(app,**kwargs):
        yield


def worker(path):
    import arknights_daily_runtime_v12 as app
    def background_only():
        app.log('[后台队列] 已禁用子进程模拟器前置调用')
        return True
    with patch.object(app,'_foreground_mumu_display',background_only):
        previous.worker(path)


if __name__=='__main__':worker(sys.argv[1])
