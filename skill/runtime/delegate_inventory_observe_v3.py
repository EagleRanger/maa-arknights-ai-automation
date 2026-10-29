"""Durable card artwork; preserve the accepted quantity/expiry/name readback."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import delegate_inventory_observe_v2 as previous
ROOT=Path(__file__).resolve().parent
ASSET=ROOT/'assets/vision/sss_delegate_card_v1.png'


def positions(path):
    import cv2,numpy as np
    image=cv2.imdecode(np.fromfile(str(path),np.uint8),1)
    tile=cv2.imdecode(np.fromfile(str(ASSET),np.uint8),1)
    if image is None or tile is None or image.shape[:2]!=(1080,1920) or tile.shape[:2]!=(120,175):return []
    scores=cv2.matchTemplate(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),cv2.cvtColor(tile,cv2.COLOR_BGR2GRAY),cv2.TM_CCOEFF_NORMED)
    result=[]
    for _ in range(6):
        _,score,_,(x,y)=cv2.minMaxLoc(scores)
        if score<.94:break
        result.append(dict(x=x,y=y,cx=x+87,cy=y+60,score=float(score)))
        scores[max(0,y-100):y+180,max(0,x-100):x+220]=0
    return result


@contextmanager
def boundary():
    with patch.object(previous,'positions',positions):yield
