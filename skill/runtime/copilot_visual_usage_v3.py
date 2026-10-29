"""Keep the sanity emblem outside the exact same-frame cost recognition ROI."""
from contextlib import contextmanager
from unittest.mock import patch
import re
import copilot_visual_usage_v1 as base
import copilot_visual_usage_v2 as previous
ORIGINAL=base.detail_cost


def detail_cost(path,items,engine):
    if path is None:return None
    import cv2,numpy as np
    frame=cv2.imdecode(np.fromfile(str(path),np.uint8),1)
    if frame is None or frame.shape[:2]!=(1080,1920):return None
    roi=cv2.cvtColor(frame[1008:1066,1760:1880],cv2.COLOR_BGR2GRAY)
    images=[cv2.cvtColor(cv2.resize(v,None,fx=4,fy=4),cv2.COLOR_GRAY2BGR)
        for v in (roi,cv2.normalize(roi,None,0,255,cv2.NORM_MINMAX))]
    class NarrowRecognizer:
        def text_recognizer(self,requested):
            if len(requested)!=2:raise ValueError('cost recognizer contract changed')
            return engine.text_recognizer(images)
    # Preserve all existing full-frame stage/mode/action/price, confidence,
    # duplicate-read and positive-cost checks; change only the crop pixels.
    normalized=[]
    for text,x,y in items:
        merged=re.fullmatch(r'(O?PERATION)(YW-EX-[1-8])',str(text).strip()) if x>1200 and 90<y<230 else None
        normalized.append((merged[1]+' '+merged[2] if merged else text,x,y))
    return ORIGINAL(path,normalized,NarrowRecognizer())


@contextmanager
def boundary(app):
    with patch.object(base,'detail_cost',detail_cost),previous.boundary(app):yield
