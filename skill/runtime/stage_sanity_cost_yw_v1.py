"""Read YW batch costs with dual-scale OCR and independent pinned stage cost.

The accepted generic reader is unchanged. Weak single readings cannot start a
battle: both multiplier reads must agree, and current total/multiplier must
equal the inspected game-data cost for the exact current YW detail page.
"""
from pathlib import Path
import hashlib
import json
import re

from stage_sanity_cost_v1 import read_cost as ORIGINAL_READ_COST, parse_cost

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "outputs/yw_20261009/candidates/catalog.json"
CATALOG_SHA = "F0BE6E6663C6C75B08549FAEC9FEFD37A08475FF2B9AFC68EEFF0B838516E264"


def consensus(total, readings, expected_cost):
    if len(readings) != 2 or any(float(score) < .55 for _, score in readings):
        return None
    texts = [str(text).strip() for text, _ in readings]
    if texts[0] != texts[1]:
        return None
    result = parse_cost(total, texts[0], proxy_plus=True)
    if not result or result["multiplier"] > 10 or result["unit_cost"] != expected_cost:
        return None
    result.update(basis="current_proxy_batch_dual_scale_plus_pinned_YW_cost",
                  multiplier_text=texts[0], multiplier_confidences=[float(s) for _, s in readings])
    return result


def read_cost(image_path, items, recognizer):
    codes = {str(t).strip().upper() for t, x, y in items
             if x >= 1200 and 90 <= y <= 230 and re.fullmatch(r"YW-[1-8]", str(t).strip().upper())}
    original = ORIGINAL_READ_COST(image_path, items, recognizer)
    if len(codes) != 1:
        return original
    raw = CATALOG.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper() != CATALOG_SHA:
        return None
    code = next(iter(codes))
    costs = [s["apCost"] for s in json.loads(raw)["stages"] if s["code"] == code]
    if len(costs) != 1 or type(costs[0]) is not int:
        return None
    if original:
        return original if original["unit_cost"] == costs[0] and original["multiplier"] <= 10 else None
    starts = [t for t, x, y in items if x >= 1550 and 930 <= y <= 1030 and "开始行动" in str(t)]
    proxy = [str(t) for t, x, y in items if 1550 <= x <= 1900 and 840 <= y <= 930
             and "代理指挥" in str(t) and ("+" in str(t) or "＋" in str(t))]
    totals = {str(t).strip() for t, x, y in items if x >= 1600 and y >= 1000
              and re.fullmatch(r"[-−–]\s*\d{1,4}", str(t).strip())}
    if not starts or not proxy or len(totals) != 1:
        return None
    from PIL import Image, ImageOps
    import numpy as np
    with Image.open(image_path) as source:
        if source.size != (1920, 1080):
            return None
        strip = source.convert("RGB").crop((1480, 871, 1552, 909))
    readings = []
    for scale in (2, 4):
        crop = ImageOps.expand(strip.resize((72*scale, 38*scale)), border=16, fill="black")
        result, _ = recognizer([np.asarray(crop)[:, :, ::-1].copy()])
        if len(result) != 1:
            return None
        readings.append(result[0])
    result = consensus(next(iter(totals)), readings, costs[0])
    if result:
        result.update(evidence=str(image_path), stage=code, expected_cost=costs[0],
                      catalog_sha256=CATALOG_SHA)
    return result
