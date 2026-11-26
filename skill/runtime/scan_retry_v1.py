"""One read-only miss policy: same frame, enlarged crops, original validator."""
from contextlib import ExitStack,contextmanager
import os
import re
import unicodedata
from unittest.mock import patch


def norm(s):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(s)).upper()).translate(
        str.maketrans('‐‑‒–—―－','-------'))


def weak_lines(path,found,engine):
    """For legacy modules which inspect OCR strings directly, repair weak boxes
    at the OCR source. Never invent a label without two agreeing local reads."""
    from poll_frames_v1 import image_of
    import cv2
    rec=getattr(engine,'text_recognizer',None)
    if not callable(rec) or not isinstance(found,(list,tuple)):return found
    candidates=[i for i,row in enumerate(found) if len(row)==3 and isinstance(row[2],(float,int))
                and row[2]<.8 and str(row[1]).strip()]
    if not candidates:return found
    try:
        img=image_of(path)
        if img is None:return found
        out=list(found);h,w=img.shape[:2]
        selected=[];crops=[]
        for i in sorted(candidates,key=lambda j:found[j][2])[:4]:
            box,old,confidence=found[i]
            xs,ys=zip(*box)
            left,right=max(0,int(min(xs))-3),min(w,int(max(xs))+4)
            top,bottom=max(0,int(min(ys))-3),min(h,int(max(ys))+4)
            if left>=right or top>=bottom:continue
            selected.append(i);crops.append(img[top:bottom,left:right])
        if not crops:return found
        first,_=rec([cv2.resize(c,None,fx=2,fy=2) for c in crops])
        if len(first or [])!=len(crops):return found
        checks=[j for j,i in enumerate(selected) if float(first[j][1])>=.93
                and norm(first[j][0]) and norm(first[j][0])!=norm(found[i][1])]
        if not checks:return found
        again,_=rec([cv2.resize(crops[j],None,fx=3,fy=3) for j in checks])
        if len(again or [])!=len(checks):return found
        for j,(text,score) in zip(checks,again):
            if float(score)>=.93 and norm(text)==norm(first[j][0]):
                i=selected[j];out[i]=(found[i][0],text,min(float(score),float(first[j][1])))
        return out
    except (OSError,ValueError,TypeError,RuntimeError,cv2.error):
        return found


def recover(app,path,rows,*,target=None,roi=None,cache=None,line_only=False):
    import cv2
    from poll_frames_v1 import image_of
    engine=getattr(app,'_ocr_engine',None)
    if not callable(engine) and not callable(getattr(engine,'text_recognizer',None)):return rows
    try:
        img=image_of(path)
        if img is None:return rows
        h,w=img.shape[:2]; l,t,r,b=roi or (0,0,w,h)
        l,t,r,b=max(0,l),max(0,t),min(w,r),min(h,b)
        if l>=r or t>=b:return rows
        wanted=norm(target) if target else None
        out=list(rows)
        def add(label,x,y):
            if not any(norm(a)==norm(label) and abs(x-i)<25 and abs(y-j)<18 for a,i,j in out):
                out.append((label,x,y))
        partial=[(norm(s),x,y) for s,x,y in rows if wanted and l<=x<r and t<=y<b
                 and len(norm(s))>=2 and norm(s)!=wanted and wanted.startswith(norm(s))]
        for prefix,x,y in partial[:3]:
            # Small fixed-height line, anchored on observed text (not an inferred digit).
            step=15 if wanted.isascii() else 30
            left=max(l,int(x-len(prefix)*step/2-24))
            right=min(r,int(x+(len(wanted)-len(prefix)/2)*step+24))
            top,bot=max(t,int(y-24)),min(b,int(y+25))
            rec=getattr(engine,'text_recognizer',None)
            if left<right and top<bot and callable(rec):
                words,_=rec(cv2.resize(img[top:bot,left:right],None,fx=3,fy=3))
                if any(norm(word)==wanted and float(conf)>=.90 for word,conf in words):
                    add(target,(left+right)//2,(top+bot)//2)
        if len(out)>len(rows) or line_only or not callable(engine):return out
        # Nothing usefully transcribed, or a glyph changed instead of dropping:
        # rediscover text boxes, transforming their centers back to screen space.
        mx,my=(l+r)//2,(t+b)//2
        areas=[(l,t,r,b)] if r-l<=960 and b-t<=600 else [
            (l,t,min(r,mx+48),min(b,my+24)),(max(l,mx-48),t,r,min(b,my+24)),
            (l,max(t,my-24),min(r,mx+48),b),(max(l,mx-48),max(t,my-24),r,b)]
        cache={} if cache is None else cache
        tile_key=('tiles',l,t,r,b)
        if tile_key not in cache:
            tiled=[]
            for x,y,xx,yy in areas:
                if int(img[y:yy,x:xx].max())-int(img[y:yy,x:xx].min())<12:continue
                found,_=engine(cv2.resize(img[y:yy,x:xx],None,fx=1.5,fy=1.5))
                for box,label,score in found or []:
                    if float(score)>=.9:
                        tiled.append((label,round(x+sum(p[0] for p in box)/len(box)/1.5),
                                      round(y+sum(p[1] for p in box)/len(box)/1.5)))
            cache[tile_key]=tiled
        for label,x,y in cache[tile_key]:
            if not wanted or norm(label)==wanted:add(target or label,x,y)
        return out
    except (OSError,ValueError,TypeError,RuntimeError,cv2.error):
        return rows


@contextmanager
def boundary(app):
    if not callable(getattr(app,'ocr',None)):
        yield;return
    last=[];old=app.ocr
    def read(path,*a,**kw):
        last.clear()
        engine=getattr(app,'_ocr_engine',None)
        if callable(engine) and isinstance(path,(str,os.PathLike)):
            class SameFrameEngine:
                def __getattr__(self,k):return getattr(engine,k)
                def __call__(self,source,*args,**kwargs):
                    found,elapsed=engine(source,*args,**kwargs)
                    if isinstance(source,(str,os.PathLike)) and os.fspath(source)==os.fspath(path):
                        found=weak_lines(path,found,engine)
                    return found,elapsed
            with patch.object(app,'_ocr_engine',SameFrameEngine()):result=old(path,*a,**kw)
        else:result=old(path,*a,**kw)
        if not result:result=recover(app,path,result or [])
        last[:]=[result,path,{}]
        return result
    def matcher(fn,region):
        def lookup(rows,label,*a,**kw):
            direct=fn(rows,label,*a,**kw)
            if direct or not last or last[0] is not rows or not isinstance(label,str):return direct
            key=(label,region)
            if key not in last[2]:
                extra=recover(app,last[1],rows,target=label,roi=region,cache=last[2])
                hits={(x,y) for s,x,y in extra[len(rows):] if norm(s)==norm(label)}
                last[2][key]=extra if len(hits)==1 else rows
            return fn(last[2][key],label,*a,**kw)
        return lookup
    from ark_modules.vision import Vision,RuntimeVisionPort
    vr=Vision.read
    def vision(self,*a,**kw):
        if not isinstance(self.port,RuntimeVisionPort) or self.port.runtime is not app:return vr(self,*a,**kw)
        base=self.port.ocr
        def identify(path):
            rows=base(path)
            if self.classify(rows)[0]=='unknown':
                return recover(app,path,rows)
            return rows
        with patch.object(self.port,'ocr',identify):return vr(self,*a,**kw)
    with ExitStack() as stack:
        stack.enter_context(patch.object(app,'ocr',read))
        for name,roi in [('find_text',None),('_event_stage_position',(100,180,1906,931)),
                         ('_find_stage_node_text',(80,140,1915,950))]:
            if hasattr(app,name):stack.enter_context(patch.object(app,name,matcher(getattr(app,name),roi)))
        for name in ('tap','swipe','back','shot'):
            if hasattr(app,name):
                fn=getattr(app,name)
                def invalidate(*a,_fn=fn,**kw):
                    last.clear()
                    return _fn(*a,**kw)
                stack.enter_context(patch.object(app,name,invalidate))
        stack.enter_context(patch.object(Vision,'read',vision))
        yield


@contextmanager
def base_state(app):
    """Attach BEFORE navigation handlers. Reclassify pixels, never replay actions."""
    original=getattr(app,'get_state',None)
    if not original or getattr(original,'__module__','')!='arknights_daily_runtime_v12':
        yield;return
    def state():
        shot=app.shot
        seen=[]
        def capture(*a,**kw):
            path=shot(*a,**kw)
            if a and a[0]=='state':seen[:]=[path]
            return path
        with patch.object(app,'shot',capture):
            value=original()
        if value!='unknown' or not seen:return value
        expanded=recover(app,seen[0],[])
        if not expanded:return value
        text=' '.join(t for t,_,_ in expanded)
        # This specific classifier has no input actions: shot("state"), OCR,
        # then predicates on the resulting text. Higher-level handlers run once.
        with patch.object(app,'shot',lambda *args:seen[0]),patch.object(app,'ocr_text',lambda p:text):
            return original()
    with patch.object(app,'get_state',state):yield
