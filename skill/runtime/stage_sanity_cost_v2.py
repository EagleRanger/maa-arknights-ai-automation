"""Read stage sanity cost with a full-frame proxy multiplier fallback.

V1 remains the first choice.  Some game fonts make RapidOCR drop the
multiplication glyph while still locating the unique multiplier digit in the
fixed proxy-plus box; accept that digit only with all page anchors present.
"""

from __future__ import annotations

import re

from stage_sanity_cost_v1 import parse_cost, read_cost as read_cost_v1


def read_cost(image_path, items, recognizer):
    starts = [
        t for t, x, y in items
        if x >= 1550 and 930 <= y <= 1030 and "开始行动" in str(t)
    ]
    proxy = [
        str(t) for t, x, y in items
        if 1550 <= x <= 1900 and 840 <= y <= 930 and "代理指挥" in str(t)
    ]
    totals = {
        str(t).strip() for t, x, y in items
        if x >= 1600 and y >= 1000 and re.fullmatch(r"[-−–]\s*\d{1,4}", str(t).strip())
    }
    multipliers = {
        int(str(t).strip()) for t, x, y in items
        if 1480 <= x <= 1560 and 860 <= y <= 920
        and re.fullmatch(r"\d{1,2}", str(t).strip())
        and 1 <= int(str(t).strip()) <= 99
    }
    if (
        starts
        and len(proxy) == 1
        and ("+" in proxy[0] or "＋" in proxy[0])
        and len(totals) == 1
        and len(multipliers) == 1
    ):
        multiplier = next(iter(multipliers))
        result = parse_cost(next(iter(totals)), f"×{multiplier}", proxy_plus=True)
        if result:
            result.update(
                evidence=str(image_path),
                multiplier_text=str(multiplier),
                multiplier_confidence=None,
                multiplier_source="full_frame_fixed_proxy_box",
            )
            return result

    return read_cost_v1(image_path, items, recognizer)
