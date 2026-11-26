"""Opt-in, two-frame ADB polling. Legacy shot() stays a file API."""
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from pathlib import Path
import os
import struct
import subprocess
import tempfile
from unittest.mock import patch


def image_of(source):
    import cv2
    import numpy as np
    if isinstance(source,np.ndarray):
        return source
    if isinstance(source,bytes):
        return cv2.imdecode(np.frombuffer(source,dtype=np.uint8),cv2.IMREAD_COLOR)
    return cv2.imdecode(np.fromfile(str(source),dtype=np.uint8),cv2.IMREAD_COLOR)


def _decoded_and_png(app):
    import cv2
    import numpy as np
    # Do not create a new MAA connection or pick a different device/backend.
    if getattr(app,'SCRIPT_SCREENSHOT_BACKEND',None)!='adb':
        return None,None
    try:
        r=subprocess.run([app.ADB,'-s',app.DEVICE,'exec-out','screencap','-p'],
            capture_output=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if (r.returncode or len(r.stdout)<24 or not r.stdout.startswith(b'\x89PNG\r\n\x1a\n')
                or r.stdout[12:16]!=b'IHDR' or struct.unpack_from('>II',r.stdout,16)!=(1920,1080)):
            return None,None
        img=cv2.imdecode(np.frombuffer(r.stdout,np.uint8),cv2.IMREAD_COLOR)
        if img is not None and img.shape==(1080,1920,3):
            return img,r.stdout
    except (OSError,subprocess.TimeoutExpired,cv2.error):
        pass
    return None,None


def capture(app):
    return _decoded_and_png(app)[0]


def retain(app, source):
    """Immutable, content-addressed proof, outside the ordinary PNG cache."""
    import cv2
    if isinstance(source,bytes):
        data=source  # the exact, already validated ADB PNG; no re-encoding
    elif isinstance(source,(str,Path)):
        p=Path(source).resolve(strict=True)
        if not p.is_relative_to(Path(app.SCREEN_DIR).resolve()):
            return str(p)  # already owned by another evidence store
        data=p.read_bytes()
    else:
        ok,encoded=cv2.imencode('.png',source)
        if not ok:raise OSError('cannot encode evidence')
        data=encoded.tobytes()
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('invalid PNG evidence')
    digest=sha256(data).hexdigest()
    dest=Path(app.OUTPUT_DIR)/'frame_evidence'/digest[:2]/(digest+'.png')
    if not dest.exists():
        dest.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=dest.parent,delete=False) as f:
            tmp=Path(f.name)
            try:f.write(data)
            except BaseException:
                f.close();tmp.unlink(missing_ok=True);raise
        try:os.replace(tmp,dest)
        finally:tmp.unlink(missing_ok=True)
    return str(dest)


def key_picture(app,source):
    try:
        return retain(app,source)
    except (OSError,ValueError) as exc:
        app.log('关键图留存失败，保留原回执：'+str(exc),'WARN')
        return None


def record_verified_stage(app,fn,prefix):
    def verify(event,display_name,*a,**kw):
        picture=None
        old=app.shot
        def capture_detail(tag,*args,**kwargs):
            nonlocal picture
            p=old(tag,*args,**kwargs)
            if tag==prefix+display_name:picture=p
            return p
        with patch.object(app,'shot',capture_detail):
            result=fn(event,display_name,*a,**kw)
        ok=result is True or (isinstance(result,tuple) and result[:1]==(True,))
        if ok and picture:
            saved=app._RUN_SUMMARY.setdefault('verified_stage_images',{})
            k=prefix+display_name
            if k not in saved:
                p=key_picture(app,picture)
                if p:saved[k]=p
        return result
    return verify


def record_verified_reward(app,fn):
    def wrapped(*a,**kw):
        result=fn(*a,**kw)
        if isinstance(result,dict) and result.get('claimed_now') is True:
            key='reward' if result.get('reward') else 'after'
            src=result.get(key)
            if isinstance(src,(str,Path)) and Path(src).suffix.lower()=='.png':
                saved=key_picture(app,src)
                if saved:
                    result[key]=saved
                    if isinstance(result.get('evidence'),list):
                        result['evidence']=[saved if p==str(src) else p for p in result['evidence']]
        return result
    return wrapped


class Pair:
    def __init__(self):
        self.clear()

    def clear(self):
        self.before=self.current=None
        self.acted=False

    def add(self,png):
        if png is not None and not isinstance(png,bytes):
            raise TypeError('history keeps only original PNG bytes')
        if not self.acted:self.before=self.current
        self.current=png  # None means acquisition failed; never reuse an obsolete frame

    def grab(self,app):
        img,png=_decoded_and_png(app)
        self.add(png)
        return img  # the caller owns the only decoded frame, just for recognition

    def before_input(self):
        self.before,self.current,self.acted=self.current,None,True

    def evidence(self,app):
        out=[]
        for kind,img in [('before_input' if self.acted else 'previous_observation',self.before),
                         ('after_input' if self.acted else 'latest_observation',self.current)]:
            if img is not None:
                out.append(dict(screenshot=retain(app,img),frame_role=kind))
        return out


@contextmanager
def startup(app):
    pair=Pair()
    def with_frames(rows):
        try:return [*(rows or []),*pair.evidence(app)]
        except (OSError,ValueError) as exc:
            app.log('启动留图不可用，保留原异常：'+str(exc),'WARN')
            return rows
    with ExitStack() as stack:
        stack.enter_context(patch.object(app,'_startup_poll_pair',pair,create=True))
        if hasattr(app,'_event_page_attention'):
            original=app._event_page_attention
            def attention(*a,**kw):
                if len(a)>=4:
                    a=(*a[:3],with_frames(a[3]),*a[4:])
                else:
                    kw['observations']=with_frames(kw.get('observations'))
                return original(*a,**kw)
            stack.enter_context(patch.object(app,'_event_page_attention',attention))
        import daily_startup_cooperation_v1 as coop
        original_publish=coop.publish_page_attention
        def publish(output,run,stage,reason,rows,*args,**kwargs):
            return original_publish(output,run,stage,reason,with_frames(rows),*args,**kwargs)
        stack.enter_context(patch.object(coop,'publish_page_attention',publish))
        try:yield pair
        finally:pair.clear()


@contextmanager
def boundary(app):
    with ExitStack() as stack:
        if hasattr(app,'NAV_DEBUG_MAX_BYTES'):
            stack.enter_context(patch.object(app,'NAV_DEBUG_MAX_BYTES',min(800_000_000,app.NAV_DEBUG_MAX_BYTES)))
        for name,prefix in [('verify_event_stage_cleared','event_verify_detail_'),
                            ('verify_event_challenge_cleared','event_challenge_verify_')]:
            if hasattr(app,name):
                stack.enter_context(patch.object(app,name,record_verified_stage(app,getattr(app,name),prefix)))
        import event_daily_reward_claim_v2 as claims
        import event_wish_wall_v1 as wall
        for module,name in [(claims,'day_card_handler'),(wall,'handler')]:
            stack.enter_context(patch.object(module,name,record_verified_reward(app,getattr(module,name))))
        # The Paradox module returns the validated settlement as its last
        # evidence item. Preserve it after verification, never an earlier card.
        from dataclasses import replace
        import paradox_simulation_v1 as insertion
        old_paradox=insertion.one_module
        def paradox(*a,**kw):
            result=old_paradox(*a,**kw)
            if result.status=='succeeded' and result.evidence:
                src=Path(result.evidence[-1])
                if src.name.startswith('paradox_settlement_') and src.suffix.lower()=='.png':
                    saved=key_picture(app,src)
                    if saved:return replace(result,evidence=(*result.evidence[:-1],saved))
            return result
        stack.enter_context(patch.object(insertion,'one_module',paradox))
        # Hot, read-only overlay probe. For a possible match (including
        # partial labels), let the original file-based action verify that
        # exact frame. Never synthesize an input from this fast path.
        if hasattr(app,'_dismiss_event_tarot_reward'):
            original=app._dismiss_event_tarot_reward
            def tarot():
                engine=getattr(app,'_ocr_engine',None)
                img=capture(app) if engine is not None else None
                if img is None:return original()
                try:
                    rows,_=engine(img)
                    words=''.join(str(row[1]) for row in rows or [])
                    if words and not any(t in words for t in ('塔罗','罗牌','已获取')):
                        return None
                except (OSError,ValueError,RuntimeError):
                    return original()
                old=app.shot
                def shot(tag,*args,**kwargs):
                    if tag=='event_tarot_probe':
                        # A possible match is not a verified reward. Use the
                        # rotating cache only when a legacy path is required.
                        import cv2
                        ok,encoded=cv2.imencode('.png',img)
                        if ok:
                            with tempfile.NamedTemporaryFile(dir=app.SCREEN_DIR,prefix=tag+'_',
                                    suffix='.png',delete=False) as f:
                                f.write(encoded.tobytes())
                                return f.name
                    return old(tag,*args,**kwargs)
                with patch.object(app,'shot',shot):return original()
            stack.enter_context(patch.object(app,'_dismiss_event_tarot_reward',tarot))
        yield
