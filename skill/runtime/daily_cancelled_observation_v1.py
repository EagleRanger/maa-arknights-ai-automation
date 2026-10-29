"""Cancel the owned OCR channel before cleanup; do not navigate after cancellation."""
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def boundary(app):
    from local_ocr_v6_small_v2 import Worker
    old_request,old_home=Worker.request,app.goto_main_menu
    cancelled=False
    def request(worker,*a,**k):
        nonlocal cancelled
        try:return old_request(worker,*a,**k)
        except (KeyboardInterrupt,SystemExit):
            cancelled=True
            app._RUN_SUMMARY['observation_cancelled']=dict(ocr_channel_closed=True,home_navigation_skipped=True)
            try:worker.close()
            except Exception as exc:
                app._RUN_SUMMARY['observation_cancelled'].update(ocr_channel_closed=False,close_error=str(exc))
            raise
    def home(*a,**k):
        return False if cancelled else old_home(*a,**k)
    with patch.object(Worker,'request',request),patch.object(app,'goto_main_menu',home):yield
