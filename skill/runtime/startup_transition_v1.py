"""Cold login only: early START evidence, one input, fresh-frame handoff."""
from contextlib import contextmanager
from pathlib import Path
import sys
import time
from unittest.mock import patch

from daily_login_visual_v1 import StartupUnverified
import poll_frames_v1 as frames


def inspect_frame(path, engine, previous=None):
    """Read only the two fixed login regions. No input and no AI calls."""
    import cv2
    import numpy as np
    frame = frames.image_of(path)
    if frame is None or frame.shape != (1080, 1920, 3):
        return 'other', None
    sample = frame[::24, ::24]
    if np.percentile(sample, 98) < 28:
        return 'dark', None
    header, button = frame[:160,:625], frame[990:1060,900:1020]
    key = tuple(cv2.resize(c,(64,24),interpolation=cv2.INTER_AREA)
                for c in (header,button,frame[290:810,520:1400]))
    if previous is not None and all(cv2.absdiff(a,b).mean()<2 for a,b in zip(key,previous)):
        return 'same_login', key
    if engine is None or np.percentile(button,98)<200:
        return 'other', key
    texts, _ = engine.text_recognizer(cv2.resize(frame[1016:1041,932:991],None,fx=4,fy=4))
    if not any(str(t).strip().upper()=='START' and float(s)>=.8 for t,s in texts):
        return 'other', key
    rows, _ = engine(header)
    labels = ''.join(str(t).replace(' ','') for _,t,s in rows or [] if float(s)>=.75)
    if '清除缓存' in labels and '网络检测' in labels:
        # An overlaid white confirm control owns input. Check the same frame
        # used for OCR; let the established full handler verify ambiguous glyphs.
        mask=cv2.inRange(frame[680:790,880:1040],(225,225,225),(255,255,255))
        shapes=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]
        if any(45<=w<=70 and 45<=h<=70 for _,_,w,h in map(cv2.boundingRect,shapes)):
            return 'other', key  # modal has input focus, not the START behind it
        return 'login', key
    return 'other', key


class ColdLogin:
    def __init__(self, app, wait, clock=time.monotonic, probe=inspect_frame):
        self.app, self.wait, self.clock, self.probe = app, wait, clock, probe
        self.sent = None
        self.login_key = None
        self.unknown_key = None
        self.home_checked = False

    def read(self, full_state):
        # Transition frames are cheap; updates, reward actions and ambiguous
        # pages still belong to the existing dispatchers, with fresh evidence.
        until = self.clock()+15
        while True:
            try:
                pair=getattr(self.app,'_startup_poll_pair',None)
                img=pair.grab(self.app) if pair is not None else None
                try:
                    kind,key=self.probe(img if img is not None else self.app.shot('login_transition'),
                                        self.app._ocr_engine,self.login_key)
                finally:
                    del img  # do not keep a full BGR frame through sleep/legacy dispatch
            except (OSError, ValueError, RuntimeError):
                kind,key='other',None
            if kind in ('login','same_login'):
                self.login_key=key
                if self.sent is None:
                    return 'login'
                # Same screen after input: never convert it to a second tap.
            elif (kind=='other' or self.clock()>=until and self.sent is None):
                if kind=='other' and self.unknown_key is not None and key is not None and self.clock()<until:
                    import numpy as np
                    if all(np.abs(a.astype('int16')-b).mean()<2 for a,b in zip(self.unknown_key,key)):
                        self.wait(1)
                        continue
                value=full_state()
                self.unknown_key=key if value=='unknown' else None
                if value=='login' and self.sent is not None:
                    pass
                elif value=='main_menu' and not self.home_checked:
                    self.wait(1)
                    value=full_state()  # late supply/announcement must take priority
                    self.home_checked=value=='main_menu'
                    return value
                else:
                    return value
            if self.sent is not None and self.clock()-self.sent >= 120:
                raise StartupUnverified('startup_after_start_unverified_120s')
            self.wait(1)


@contextmanager
def boundary(app):
    # Only the frozen bootstrap's direct wait(15)/get_state/tap call sites
    # belong to us. Nested update/overlay handlers and warm business calls
    # keep their original timing, and other modules keep their input owners.
    if not all(hasattr(app,k) for k in ('ensure_env','wait','tap','get_state','__file__')):
        yield
        return
    old_ensure=app.ensure_env
    def ensure(*args,**kwargs):
        old_wait,old_tap,old_state=app.wait,app.tap,app.get_state
        cold=ColdLogin(app,old_wait)
        enabled=False
        path=Path(app.__file__).resolve()
        def bootstrap(frame):
            return frame.f_code.co_name=='ensure_env' and Path(frame.f_code.co_filename).resolve()==path
        def wait(seconds,*a,**kw):
            nonlocal enabled
            if seconds==15 and bootstrap(sys._getframe(1)):
                enabled=True
                # The old post-click sleep is immediately followed by another
                # loop sleep. Keep slow-device budgets inside the observation.
                return old_wait(.5)
            return old_wait(seconds,*a,**kw)
        def state(*a,**kw):
            if enabled and bootstrap(sys._getframe(1)):
                return cold.read(lambda:old_state(*a,**kw))
            return old_state(*a,**kw)
        def tap(x,y,*a,**kw):
            if enabled and (x,y)==(961,1028) and bootstrap(sys._getframe(1)):
                if cold.sent is not None:
                    return
                if app._maa_task_queue_running() is not False:
                    raise StartupUnverified('startup_queue_not_idle')
                cold.sent=cold.clock()
                pair.before_input()
                app.log('[启动转场] START 已确认，发送一次，随后只观察页面变化')
            return old_tap(x,y,*a,**kw)
        with frames.startup(app) as pair, patch.object(app,'wait',wait),patch.object(app,'get_state',state),patch.object(app,'tap',tap):
            return old_ensure(*args,**kwargs)
    with patch.object(app,'ensure_env',ensure):
        yield
