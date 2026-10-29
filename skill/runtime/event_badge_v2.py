"""Colour-independent normal-star verification for the current SR-EX detail UI.

The former detector assumes both a fixed upper-right geometry and cyan lit
badges.  The 2026-09-17 SR-EX-1 detail screenshot proves that this event uses
three saturated gold badges at a different, but stable, geometry.  The test
below deliberately measures brightness and saturation, not the hue name.
"""

from __future__ import annotations


_NORMAL_BADGE_CENTERS = (0.655, 0.700, 0.745)


def current_detail_normal_badge_ratios(image_path):
    """Return the three independent lit-fill ratios for the current detail UI."""
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    values = []
    for center in _NORMAL_BADGE_CENTERS:
        roi = image.crop((
            int(width * (center - 0.022)), int(height * 0.180),
            int(width * (center + 0.022)), int(height * 0.285),
        ))
        pixels = list(roi.getdata())
        if not pixels:
            values.append(0.0)
            continue
        lit = sum(
            1 for red, green, blue in pixels
            if max(red, green, blue) > 155
            and max(red, green, blue) - min(red, green, blue) > 65
        )
        values.append(lit / len(pixels))
    return tuple(values)


def current_detail_normal_badges_complete(image_path, *, threshold=0.08):
    ratios = current_detail_normal_badge_ratios(image_path)
    return bool(ratios) and min(ratios) >= threshold


def install_normal_badge_detector(runtime) -> None:
    """Layer the new geometry over, rather than edit, the frozen V12 runtime."""
    if getattr(runtime, "_event_badge_v2_installed", False):
        return
    legacy = runtime._event_normal_badges_ratio

    def normal_badges_ratio(image_path):
        old_ratio = legacy(image_path)
        current = min(current_detail_normal_badge_ratios(image_path), default=0.0)
        return max(old_ratio, current)

    runtime._event_normal_badges_ratio = normal_badges_ratio
    runtime._event_badge_v2_installed = True
