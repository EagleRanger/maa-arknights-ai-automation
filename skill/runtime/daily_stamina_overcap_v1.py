"""Read labelled live sanity, including valid values above the natural cap.

The natural cap (210) is not a bound on stocked sanity. Keep the old fallback
for unrecognised screens, but do not discard an anchored 450/210 observation.
No navigation, refill, or expenditure is added by this adapter.
"""
from contextlib import contextmanager
from functools import wraps
import re


def terminal_value(items, width, height):
    card = [(str(t).strip(), x / width, y / height) for t, x, y in items
            if .54 <= x / width <= .72 and .16 <= y / height <= .41]
    if not any('理智' in t and '210' in t for t, _, _ in card):
        return None
    values = [int(t.lstrip('+')) for t, _, y in card
              if re.fullmatch(r'\+?\d{1,3}', t) and .18 <= y <= .32]
    return values[0] if len(values) == 1 else None


def explicit_value(text):
    values = [int(m.group(1)) for m in
              re.finditer(r'(?<![\d/])(\d{1,3})\s*/\s*210(?!\d)', text)]
    return values[0] if len(set(values)) == 1 else None


def install(runtime):
    original = runtime.get_stamina
    if getattr(original, '_stamina_overcap_v1', False):
        return runtime

    @wraps(original)
    def read():
        from PIL import Image
        p = runtime.shot('stamina_labelled_current')
        with Image.open(p) as frame:
            value = terminal_value(runtime.ocr(p), *frame.size)
        if value is None:
            value = explicit_value(runtime.ocr_text(p))
        if value is None:
            return original()
        # An anchored over-cap stock is real current evidence, not passive
        # recovery from a historical farm checkpoint (whose validator caps 210).
        # Expenditure is still reconciled separately from this observation.
        checked = value if value > 210 else runtime._validate_stamina_ocr_against_event_checkpoint(value)
        if checked is not None:
            runtime.log(f'  [V85/实时理智] 标签/比例实证 {checked}/210；自然上限不是库存上限')
        return checked

    read._stamina_overcap_v1 = True
    read._wrapped = original
    runtime.get_stamina = read
    runtime._RUN_SUMMARY['stamina_read_policy'] = {
        'version': 'overcap_v1', 'natural_cap_is_not_stock_limit': True,
        'source': 'current_game_label_or_explicit_ratio', 'max_ocr_digits': 3,
        'refill_actions': 0,
    }
    return runtime


@contextmanager
def engine_boundary(runtime):
    old_main, old_read = runtime.main, runtime.get_stamina
    @wraps(old_main)
    def main(*args, **kwargs):
        install(runtime)
        return old_main(*args, **kwargs)
    runtime.main = main
    try:
        yield
    finally:
        runtime.main, runtime.get_stamina = old_main, old_read
