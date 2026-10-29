"""Read current SSS best-record fraction without the obsolete '通关于' lock rule."""
import re


def consensus(readings):
    seen = []
    for index, (text, score) in enumerate(readings):
        match = re.fullmatch(r'([0-6])\s*/\s*6', str(text).strip())
        if match and float(score) >= .8:
            seen.append({'view': index, 'cleared': int(match[1]), 'text': text, 'confidence': float(score)})
    values = {row['cleared'] for row in seen}
    if len(seen) < 2 or len(values) != 1:
        return {'verified': False, 'reason': 'record_conflict_or_missing', 'readings': seen}
    return {'verified': True, 'cleared': next(iter(values)), 'total': 6, 'readings': seen}


def read_record(path, engine):
    import cv2
    import numpy as np
    frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2] != (1080, 1920):
        return {'verified': False, 'reason': 'unsupported_frame'}
    images = []
    for x1, y1, x2, y2 in ((1715, 42, 1820, 103), (1700, 28, 1823, 114), (1720, 45, 1816, 99)):
        grey = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        for value in (grey, cv2.normalize(grey, None, 0, 255, cv2.NORM_MINMAX)):
            images.append(cv2.cvtColor(cv2.resize(value, None, fx=4, fy=4), cv2.COLOR_GRAY2BGR))
    rows, _ = engine.text_recognizer(images)
    result = consensus(rows)
    result['evidence'] = str(path)
    return result


def classify(items, record, region):
    text = ''.join(str(label).replace(' ', '') for label, _, _ in items)
    if region not in text or '周期清理记录' not in text or '全权委托' not in text:
        return {'status': 'unverified', 'reason': 'wrong_detail_page'}
    if any(marker in text for marker in ('不使用好友助战', '通关后解锁', '解锁全权委托', '委托暂不可用')):
        return {'status': 'locked', 'reason': 'explicit_lock'}
    if record.get('verified') is not True:
        return {'status': 'unverified', 'reason': 'best_record_not_verified'}
    if record.get('cleared') != 6:
        return {'status': 'incomplete_record', 'reason': 'prefer_complete_six_stage_delegation'}
    positions = [(x, y) for label, x, y in items if str(label).replace(' ', '') == '全权委托']
    if len(positions) != 1:
        return {'status': 'unverified', 'reason': 'delegate_not_unique'}
    return {'status': 'available', 'position': positions[0], 'reason': 'current_six_of_six_no_lock'}
