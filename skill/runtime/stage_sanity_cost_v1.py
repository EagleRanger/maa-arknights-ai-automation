"""Read current stage cost; a proxy batch total is not a single-stage cost.

Only reads the supplied frame. Does not navigate, click, or infer from old runs.
"""
import re


def parse_cost(total_text, multiplier_text=None, *, proxy_plus=False):
    total_match = re.fullmatch(r'[-−–]\s*(\d{1,4})', str(total_text).strip())
    if not total_match:
        return None
    total = int(total_match[1])
    multiplier = 1
    if proxy_plus:
        match = re.fullmatch(r'[×xX*]\s*(\d{1,2})', str(multiplier_text).strip())
        if not match or not 1 <= int(match[1]) <= 99:
            return None
        multiplier = int(match[1])
    elif multiplier_text is not None:
        return None
    if total % multiplier or not 1 <= total // multiplier <= 40:
        return None
    return {'total_cost': total, 'multiplier': multiplier,
            'unit_cost': total // multiplier,
            'basis': 'current_proxy_batch' if proxy_plus else 'current_single_stage'}


def read_cost(image_path, items, recognizer):
    """1920x1080 normalized stage detail, with start/proxy label anchors."""
    starts = [t for t,x,y in items if x >= 1550 and 930 <= y <= 1030 and '开始行动' in str(t)]
    proxy = [str(t) for t,x,y in items if 1550 <= x <= 1900 and 840 <= y <= 930
             and '代理指挥' in str(t)]
    totals = {str(t).strip() for t,x,y in items if x >= 1600 and y >= 1000
              and re.fullmatch(r'[-−–]\s*\d{1,4}', str(t).strip())}
    if not starts or not proxy or len(totals) != 1:
        return None
    plus = any('+' in t or '＋' in t for t in proxy)
    multiplier_text = None
    confidence = None
    if plus:
        # The full-frame detector can miss the small x8. Recognize the precise
        # multiplier strip directly, retaining the multiplication sign.
        from PIL import Image, ImageOps
        import numpy as np
        with Image.open(image_path) as source:
            if source.size != (1920, 1080):
                return None
            crop = source.convert('RGB').crop((1480, 871, 1552, 909))
        crop = ImageOps.expand(crop.resize((144, 76)), border=16, fill='black')
        result, _ = recognizer([np.asarray(crop)[:, :, ::-1].copy()])
        if len(result) != 1:
            return None
        multiplier_text, confidence = result[0]
        if float(confidence) < 0.60:
            return None
    result = parse_cost(next(iter(totals)), multiplier_text, proxy_plus=plus)
    if result:
        result.update(evidence=str(image_path), multiplier_text=multiplier_text,
                      multiplier_confidence=float(confidence) if confidence is not None else None)
    return result
