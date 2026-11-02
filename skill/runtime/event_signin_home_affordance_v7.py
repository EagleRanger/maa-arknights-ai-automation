"""Add the observed Oct31 home dropdown variant, retaining V6 navigation."""
from pathlib import Path
import hashlib
import event_signin_discovery_v6 as previous

OLD_CONTROL = previous.home_control
from portable_resources_v1 import local_visual_path


def home_control(path, items, kind='folded'):
    result = OLD_CONTROL(path, items, kind)
    if result or kind != 'folded' or not previous.home_anchors(items):
        return result
    import cv2
    import numpy as np
    reference = local_visual_path('signin_folded_v7')
    if reference is None:
        return None
    actual = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    source = cv2.imdecode(np.fromfile(str(reference), dtype=np.uint8), cv2.IMREAD_COLOR)
    if actual is None or actual.shape[:2] != (1080, 1920):
        return None
    white = lambda a: np.uint8(np.all(a > 205, axis=2))*255
    template = white(source)
    search = white(actual[170:265, 0:150])
    if template.std() < 5:
        return None
    scores = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, confidence, _, point = cv2.minMaxLoc(scores)
    if confidence < .92:
        return None
    return dict(point=(point[0]+41, 170+point[1]+17), confidence=round(confidence, 4),
                kind='folded_oct31', frame=str(path))
