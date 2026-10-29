"""Same #12 footer split-number OCR; do not reinterpret818 as8/8."""
from unittest.mock import patch
import re
import sss_reward_pages_v2 as previous


def footer_fraction(app,path,items):
    if not any(str(t).replace(' ','')=='当前任务进度' and x>1600 and y>900 for t,x,y in items):return None
    import cv2,numpy as np
    frame=cv2.imdecode(np.fromfile(str(path),np.uint8),1)
    if frame is None or frame.shape[:2]!=(1080,1920):return None
    values=[]
    for x,y,a,b in ((1735,985,1820,1060),(1838,990,1897,1060)):
        roi=cv2.cvtColor(frame[y:b,x:a],cv2.COLOR_BGR2GRAY)
        images=[cv2.cvtColor(cv2.resize(v,None,fx=4,fy=4),cv2.COLOR_GRAY2BGR)
            for v in (roi,cv2.normalize(roi,None,0,255,cv2.NORM_MINMAX))]
        rows,_=app._ocr_engine.text_recognizer(images)
        valid=[int(t) for t,s in rows if re.fullmatch(r'\d{1,2}',str(t)) and s>=.85]
        if len(valid)!=2 or len(set(valid))!=1:return None
        values.append(valid[0])
    completed,total=values
    return (completed,total) if 0<=completed<=total and total>0 else None


def service(app,regions,completed_audit=None):
    original=previous._task_fraction
    def read(runtime,path,items):
        result=original(runtime,path,items)
        return result if result is not None else footer_fraction(runtime,path,items)
    with patch.object(previous,'_task_fraction',read):
        return previous.service(app,regions,completed_audit=completed_audit)
