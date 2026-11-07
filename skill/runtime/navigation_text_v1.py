"""Context-bound navigation labels, not prices, counters or claim evidence."""
from dataclasses import dataclass
from functools import lru_cache
import os
import re
import unicodedata


@lru_cache(maxsize=256)
def simplified(text):
    # Windows already ships this conversion. Do not add an OCR/model dependency.
    if os.name == 'nt':
        import ctypes
        fn = ctypes.windll.kernel32.LCMapStringEx
        fn.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_wchar_p,
                       ctypes.c_int, ctypes.c_wchar_p, ctypes.c_int,
                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t]
        fn.restype = ctypes.c_int
        size = fn('zh-CN', 0x02000000, text, len(text), None, 0, None, None, 0)
        if size:
            out = ctypes.create_unicode_buffer(size + 1)
            if fn('zh-CN', 0x02000000, text, len(text), out, size, None, None, 0):
                return out.value
    # Portable fallback covers the currently used UI vocabulary, not all Chinese.
    return text.translate(str.maketrans('時間見證戰時新聞委員會結束終端編隊幹員採購公開招募倉庫活動任務獎勵報領取',
                                      '时间见证战时新闻委员会结束终端编队干员采购公开招募仓库活动任务奖励报领取'))


def key(text):
    text = simplified(unicodedata.normalize('NFKC', str(text))).casefold()
    return ''.join(c for c in unicodedata.normalize('NFKD', text)
                   if not c.isspace() and unicodedata.category(c)[0] not in 'PM'
                   and unicodedata.category(c) != 'Cf')


def distance(left, right):
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        nxt = [i]
        for j, b in enumerate(right, 1):
            nxt.append(min(nxt[-1]+1, row[j]+1, row[j-1]+(a != b)))
        row = nxt
    return row[-1]


def same_label(actual, expected, *, contextual=False):
    a, b = key(actual), key(expected)
    if not a or not b:
        return False
    if a == b:
        return True
    if not contextual or re.findall(r'\d+', a) != re.findall(r'\d+', b):
        return False
    # Similar spelling must not invert a state/direction or a numbered identity.
    if any((word in a) != (word in b) for word in ('未', '已', '不', '无', '向前', '向后')):
        return False
    # No universal percentage: a short label cannot lose a character safely;
    # a longer title has room for one OCR edit (two only for long sentences).
    length = min(len(a), len(b))
    budget = 2 if length >= 12 else 1 if length >= 5 else 0
    return budget > 0 and distance(a, b) <= budget


@dataclass(frozen=True)
class Target:
    text: str
    rect: tuple


def candidates(rows, target):
    l, t, r, b = target.rect
    return [(str(s), x, y) for s, x, y in rows
            if l <= x <= r and t <= y <= b
            and same_label(s, target.text, contextual=True)]


def crop_read(app, path, rect, scale=2):
    import cv2
    import numpy as np
    engine = getattr(app, '_ocr_engine', None)
    if not callable(engine):
        return []
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), 1)
    l, t, r, b = rect
    if image is None or image.shape[:2] != (1080, 1920):
        return []
    enlarged = cv2.resize(image[t:b, l:r], None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_CUBIC)
    data, _ = engine(enlarged)
    return [(str(text), l + sum(p[0] for p in box)/len(box)/scale,
             t + sum(p[1] for p in box)/len(box)/scale)
            for box, text, score in (data or []) if float(score) >= .5]


def recover(app, path, rows, target, read, context):
    """Full read -> enlarged ROI -> fresh full/ROI; never click or close here."""
    notes = app._RUN_SUMMARY.setdefault('navigation_text', [])
    for attempt in range(2):
        hits = candidates(rows, target)
        for method in ('full', 'crop2x'):
            if method == 'crop2x':
                if len(hits) > 1:
                    break
                try:
                    recovered = crop_read(app, path, target.rect)
                except (OSError, ValueError, RuntimeError):
                    recovered = []
                hits = candidates(recovered, target)
            if len(hits) == 1:
                raw, x, y = hits[0]
                notes.append(dict(path=str(path), target=target.text, raw=raw,
                                  normalized=key(raw), method=method, attempt=attempt))
                l, t, r, b = target.rect
                return [(s, a, c) for s, a, c in rows if not (l <= a <= r and t <= c <= b)] + [(target.text, x, y)]
        notes.append(dict(path=str(path), target=target.text, method='unresolved',
                          attempt=attempt, candidates=len(hits), raw_candidates=hits))
        if len(hits) > 1:
            # Returning these rows would let an older exact matcher silently
            # choose one of two near-identical candidates.
            raise RuntimeError('导航候选不唯一，保留当前页交给执行AI')
        if attempt:
            return rows
        path = str(app.shot('tl_tasks_navigation_retry'))
        rows = read(path)
        if not context(rows):
            return rows
    return rows
