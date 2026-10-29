"""Select the first available low-trust card in verified ascending UI; no confirm."""
import re
from pathlib import Path
from activity_room_invite_v1 import blue_card_bounds


def ascending_arrow(path):
    import cv2
    import numpy as np
    import hashlib
    source = Path(__file__).resolve().parent/'assets/activity_room_visual_v1/trust_ascending_reference.png'
    if (not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() !=
            '13f8ce21c9dca216e85f02c71318f5951453b0d3b59143f631d5d78650f5a534'):
        return False
    masks = []
    for p in (source, Path(path)):
        a = cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if a is None or a.shape[:2] != (1080, 1920): return False
        masks.append(cv2.inRange(cv2.cvtColor(a[60:90,1550:1600], cv2.COLOR_BGR2HSV),
                                 (85, 120, 100), (115, 255, 255)) > 0)
    union = np.logical_or(*masks).sum()
    return bool(union > 20 and np.logical_and(*masks).sum()/union >= .95)


def candidates(values):
    cards = []
    for col in range(6):
        x1, x2 = 565+219*col, 768+219*col
        for row, (y1, y2) in enumerate(((112, 526), (538, 930))):
            subset = [(t,x,y) for t,x,y in values if x1 < x < x2 and y1 < y < y2]
            trust = list({int(m[1]) for t,x,y in subset if y > y2-60
                     if (m := re.search(r'(?<!\d)(\d{1,3})\s*%$', t.strip()))})
            if len(trust) > 1: return []
            occupied = any(re.search(r'B\d{3}|ACTIVITY',t, re.I) for t,x,y in subset)
            cards.append(dict(trust=trust[0] if trust else None, occupied=occupied, center=((x1+x2)//2, (y1+y2)//2)))
    known = [c['trust'] for c in cards if c['trust'] is not None]
    if known != sorted(known): return []
    # Ascending arrow is separately verified. Only the prefix through the first
    # available card matters; unread cards after that cannot be a lower choice.
    for card in cards:
        if card['trust'] is None: return []
        if not card['occupied'] and card['trust'] < 200: return [card]
    return []


def card_trust_ocr(path):
    """Twelve known card-foot ROIs; missing text stays unknown, never zero."""
    import cv2
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    a = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if a is None or a.shape[:2] != (1080, 1920): return []
    reader = RapidOCR(); values = []
    for col in range(6):
        for row, y in enumerate((485, 900)):
            x = 650+219*col
            roi = cv2.resize(a[y-20:y+23, x-29:x+81], None, fx=3, fy=3)
            found, _ = reader(roi)
            digits = {int(m[1]) for box,t,c in (found or []) if float(c) >= .65
                      if (m := re.search(r'(?<!\d)(\d{1,3})\s*%', t))}
            if len(digits) == 1: values.append((str(digits.pop())+'%', x, y))
    return values


def select(runtime):
    result = dict(status='blocked', confirmation_sent=False)
    if runtime._maa_task_queue_running() is not False: return dict(result, reason='queue_not_idle')
    before = runtime.shot('activity_trust_select_before'); values = runtime.ocr(before)
    if not ascending_arrow(before): return dict(result, reason='ascending_trust_arrow_required', before=before)
    values += card_trust_ocr(before)
    options = candidates(values)
    if not options: return dict(result, reason='ascending_available_prefix_required', before=before)
    target = options[0]; runtime.tap(*target['center']); runtime.wait(1)
    after = runtime.shot('activity_trust_selected_detail'); values = runtime.ocr(after)
    bounds, size = blue_card_bounds(after)
    names = [t for t,x,y in values if x < 500 and 150 < y < 225 and re.fullmatch(r'[\u4e00-\u9fff·]+', t)]
    if len(bounds) != 1 or len(names) != 1: return dict(result, reason='selected_name_or_blue_card_required', after=after)
    return dict(status='trust_candidate_selected', operator=names[0], trust_percent=target['trust'],
                before=before, after=after, confirmation_sent=False)
