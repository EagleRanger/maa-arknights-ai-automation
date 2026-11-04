"""Read-only OCR recovery; known actions and original-owner AI handoff remain."""
from contextlib import contextmanager
from unittest.mock import patch
from ark_modules import vision


def navigation_home(items):
    """Navigation does not require a perfect account-ID label or terminal font."""
    regions={'采购中心':(1080,600,1420,825),'公开招募':(1380,650,1660,840),
             '基建':(1320,780,1680,1040),'仓库':(1650,800,1910,1060),
             '干员':(1330,410,1650,610),'编队':(1000,410,1320,620)}
    hits=set();terminal=False
    for t,x,y in items:
        label=str(t).replace(' ','').replace('編隊','编队').replace('終端','终端')
        if 450<x<1500 and 150<y<920 and any(k in label for k in (
                '确认退出','确定退出','离开罗德岛','确认升级','获得物资','配给',
                '签到','许愿墙','活动公告','系统公告','确定','取消')):
            return False
        if label=='终端' and 1300<x<1600 and 100<y<420:terminal=True
        if label in regions:
            a,b,c,d=regions[label]
            if a<=x<=c and b<=y<=d:hits.add(label)
    return len(hits)>=5 or (terminal and len(hits)>=4)


def line_items(app,path,rect,scale=2):
    """Known one-line ROI only: reuse the selected recognizer, not a new model."""
    import cv2,numpy as np
    source=cv2.imdecode(np.fromfile(str(path),dtype=np.uint8),1)
    a,b,c,d=rect
    if source is None or source.shape[:2]!=(1080,1920) or not (0<=a<c<=1920 and 0<=b<d<=1080):
        return []
    engine=getattr(app,'_ocr_engine',None)
    recognize=getattr(engine,'text_recognizer',None)
    if not callable(recognize):return []
    crop=cv2.resize(source[b:d,a:c],None,fx=scale,fy=scale)
    rows,_seconds=recognize([crop])
    return [(str(text),(a+c)/2,(b+d)/2) for text,score in rows if float(score)>=.5]


def tolerant_read(self,tag):
    """Unknown is re-observed, not an immediate terminal signal or new click."""
    paths=[];unknown=0
    for n in range(self.max_frames):
        path,at=self.port.capture(f'{tag}_{n}')
        if at.tzinfo is None or not 0<=(self.port.now()-at).total_seconds()<=5:
            raise ValueError('stale capture')
        values=tuple(self.port.ocr(path));kind,positions=self.classify(values)
        paths.append(str(path));frame=vision.Frame(str(path),at,values,kind,positions or {})
        if kind not in ('unknown','transition'):return frame,tuple(paths)
        if kind=='unknown':
            unknown+=1
            if unknown>=3:return frame,tuple(paths)
        if n+1<self.max_frames:self.port.wait(.5)
    return frame,tuple(paths)


@contextmanager
def boundary(app):
    original_state=app.get_state;original_home=app.goto_main_menu
    original_recover=app._wait_unknown_navigation_page
    original_classify=vision.classify_existing
    def classify(items):
        if navigation_home(items):return 'home',{}
        return original_classify(items)
    def state():
        # Re-run the real consumer; never replay its previous OCR array.
        for attempt in range(3):
            metrics=app._RUN_SUMMARY.setdefault('ocr_tolerance',{})
            metrics['state_reads']=metrics.get('state_reads',0)+1
            value=original_state()
            if value!='unknown':return value
            app._RUN_SUMMARY.setdefault('ocr_tolerance',{}).setdefault('unknown_state_reads',0)
            app._RUN_SUMMARY['ocr_tolerance']['unknown_state_reads']+=1
            if attempt<2:app.wait(.5)
        return value
    def home():
        current=original_state()
        if current not in ('unknown','main_menu','terminal_list'):
            return original_home()
        p=app.shot('navigation_home_shape')
        if navigation_home(app.ocr(p)):return True
        return original_home()
    def recover():
        if app._maa_task_queue_running() is not False:return original_recover()
        port=vision.RuntimeVisionPort(app,lambda:bool(app._RUN_MUTEX_HANDLE))
        reader=vision.Vision(port,classify,vision.existing_home_transitions(),max_frames=3)
        proof=reader.reach('home')
        if proof.status=='succeeded':return True
        wait=getattr(app,'_startup_ai_wait',None)
        if not callable(wait):return original_recover()
        def verify():
            p=app.shot('navigation_ai_recheck')
            ready=navigation_home(app.ocr(p)) and app._maa_task_queue_running() is False
            return dict(ok=ready,read_only=True,state='main_menu' if ready else 'unknown',evidence=[str(p)])
        wait('navigation_ocr_unverified_preserve_scene',verify)
        return verify()['ok']
    with patch.object(app,'get_state',state),patch.object(app,'goto_main_menu',home), \
         patch.object(app,'_wait_unknown_navigation_page',recover), \
         patch.object(vision.Vision,'read',tolerant_read), \
         patch.object(vision,'classify_existing',classify):
        yield


def run_composed(operation,app):
    # Install after the legacy installers, at the actual daily-engine seam.
    import run_daily as engine
    original=engine.main
    def main(*args,**kwargs):
        with boundary(app):return original(*args,**kwargs)
    with patch.object(engine,'main',main):return operation()
