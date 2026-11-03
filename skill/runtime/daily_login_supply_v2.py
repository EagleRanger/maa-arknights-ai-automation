"""Today's supply title + visible confirmation tick; reward contents are irrelevant."""
from contextlib import contextmanager
from unittest.mock import patch
import base64
import zlib
import daily_login_supply_v1 as previous

# 36px grayscale UI-only confirmation glyph, from the retained 2026-11-03
# failure frame. No account, rewards, background or personal screenshot.
TICK = 'eJx11Nt2mkAUBuCbwgxnGE4aTdSmpomHLBAaiSYqDKKoOTRmtVe96Pu/RGcG0CRd+W/91mbvPTNGC4z9E11VFVWWJFGAgIYn4Theavjh8KJ9n+Ghq2nEyLIkHg3HItS9cNDF6dDUPhq+MhyoeaMeDh1CNIUY+ilm+KPhwEngR02NGUVhZf4znPg1bBvMfPYtEq1v6vpnRhDKloyDUd7PxVu9K4tSXjQKpJK82Q8J8pK5ZwOOB5AanRrTNWQ6GP0dKqju4WyZDmUOqMbBuKfWwQB0OUmWWZ55KgeQfTCGqR3r1Cf5apllURNyQJL0kqjlElk/1ihdpikeE0J3VRi74bCWmYGOFydxgm9OIJmKTMiIO8JhrTLQJmQeJ+MGKJbIU+IEu/1DYBfnBS0/ThaL+EA4jn7rW75/3W9HLjWC4yUFgdwbY1Dz+pz7SBREx49xHCeTJvxSiqJn29/tX552y74uul6MkySedIQKlHPprrf5+bRZL65Or2ekSHLbFtldLUNXqKvmYPPymKfTm8lsTsgpna8EAEJULMj0fv19zRb3c4zTaUfUHbUy0LBReRbu9M/vHMfkIKcdGaLa0ZiOUZyqrrneepuvVqtpSwJQlIWqGSBKB6OhwerxYUsIrO5ipdABKfZ1/jBry/CjEUyjiE6v2ZXfUqDA0JHwqHkwmqpohsKez9HQx9Md1QwDVYU+vENmQCPIBg5CJgntij6O4ikKZVcA2H6U40vLtEhME9FaR0UZ2fEgGi3z5Ltj2STWO0SvG4QC6kXhIFlv0n7ddpxa3WFII0ZWddo8uSnDcRh4M7zarsNWzW11m3ZVSXUaiNRSzoLb0L+f3d7F690uHpy1zxvMsL80u25IqtsbR8GwH978iO6W293zdtJr1W3SNzNkUYbTHU2ioH9x3mn/A+UwdDU='


def supply_items(items, path):
    title = ''.join(''.join(str(t).split()) for t,x,y in items
                    if 650 <= x <= 1250 and 150 <= y <= 330)
    if title not in ('今日配给', '每日配给'):
        return items, False
    if confirm_tick(path) is None:
        return items, False
    if any(str(t)=='今日配给' for t,_,_ in items):
        return items, True
    return [*items,('今日配给',960,235)], True


def confirm_tick(path):
    import cv2
    import numpy as np
    from PIL import Image
    try:
        with Image.open(path) as im:
            if im.size != (1920,1080):return None
            roi=np.array(im.convert('L').crop((900,900,1020,1030)).resize((60,65)))
    except (OSError,ValueError,TypeError):
        return None
    template=np.frombuffer(zlib.decompress(base64.b64decode(TICK)),dtype=np.uint8).reshape(36,36)
    score, point = cv2.minMaxLoc(cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED))[1::2]
    if score < .78:return None
    return (round(900+(point[0]+18)*2),round(900+(point[1]+18)*2))


@contextmanager
def boundary(app):
    # Keep the mature startup scope, existing dismiss action and fresh-home
    # verification. Only replace the item-dependent classifier at its consumer.
    old_ocr=app.ocr
    latest=None
    def observed(path):
        nonlocal latest
        latest=path
        return old_ocr(path)
    with patch.object(app,'ocr',observed), \
         patch.object(previous,'supply_items',lambda items:supply_items(items,latest)), \
         previous.boundary(app):
        yield
