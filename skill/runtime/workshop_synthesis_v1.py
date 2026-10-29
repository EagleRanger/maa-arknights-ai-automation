"""One observed workshop batch; no navigation, worker selection or daily flow."""
from pathlib import Path
import json
import re

RECIPES = {
    '碳素': ('碳', 3, 0, 2),
    '碳素组': ('碳素', 3, 0, 4),
    '高级加固建材': ('碳素组', 2, 7200, 4),
}


def _unique(items, bounds, pattern):
    x0, y0, x1, y1 = bounds
    found = []
    for text, x, y in items:
        if x0 < x < x1 and y0 < y < y1:
            match = re.fullmatch(pattern, re.sub(r'\s+', '', text))
            if match:
                found.append(match)
    return found[0] if len(found) == 1 else None


def confirmation(items, expected, width, height):
    """Only the observed 1080p B105 synthesis layout, exact costs and batch."""
    if (width, height) != (1920, 1080):
        return None
    if not _unique(items, (560, 0, 1000, 120), r'加工站B105[0OIl1|]*'):
        return None
    product, ingredient = expected['product'], expected['ingredient']
    quantity = expected['quantity']
    recipe = RECIPES.get(product)
    if (type(quantity) is not int or not 1 <= quantity <= 8 or recipe is None
            or ingredient != recipe[0] or expected['input_count'] != recipe[1]*quantity
            or expected['lmd_cost'] != recipe[2]*quantity or expected['mood_cost'] != recipe[3]*quantity):
        return None
    if not _unique(items, (700, 780, 1120, 885), re.escape(product)):
        return None
    if not _unique(items, (780, 270, 1080, 350), re.escape(ingredient)):
        return None
    batch = _unique(items, (1530, 490, 1800, 610), r'(\d+)')
    stock = _unique(items, (820, 425, 1010, 490), r'(\d+)[/／](\d+)')
    mood = _unique(items, (200, 700, 340, 800), r'(\d+)[/／]24')
    currency = _unique(items, (1490, 305, 1620, 370), r'(\d+)')
    cost = _unique(items, (1700, 305, 1850, 370), r'(\d+)')
    buttons = [(x, y) for t, x, y in items if t.strip() == '开始加工' and x > 1450 and y > 885]
    if not all((stock, mood, currency)) or len(buttons) != 1:
        return None
    # The recipe was read from the actual formula list. If the isolated mood
    # glyph is absent, explicit count AND scaled ingredient cost uniquely
    # establish the conservative fee. A visible conflicting fee still rejects.
    inferred_mood = cost is None and batch is not None and int(batch[1]) == quantity and int(stock[2]) == expected['input_count']
    if cost is None and not inferred_mood:
        return None
    mood_cost = int(cost[1]) if cost else expected['mood_cost']
    # Large hollow count glyphs can be absent from OCR. Exact total ingredient
    # cost AND total mood independently imply the batch under this recipe.
    if ((batch is not None and int(batch[1]) != quantity) or int(stock[2]) != expected['input_count']
            or int(stock[1]) < int(stock[2]) or int(currency[1]) != expected['lmd_cost']
            or mood_cost != expected['mood_cost'] or int(mood[1]) < mood_cost):
        return None
    return dict(button=buttons[0], input_before=int(stock[1]), input_cost=int(stock[2]),
                mood_before=int(mood[1]), mood_cost=mood_cost, mood_cost_basis='observed_recipe_count_and_input' if inferred_mood else 'visible_fee', lmd_cost=int(currency[1]), quantity=quantity,
                quantity_basis='visible_count_and_costs' if batch else 'exact_scaled_input_and_mood_costs')


def commit_one(runtime, expected, output):
    directory = Path(output); directory.mkdir(parents=True, exist_ok=True)
    receipt = directory/'synthesis_receipt.json'
    if receipt.is_file():
        old = json.loads(receipt.read_text(encoding='utf-8'))
        if old.get('confirmation_sent') is True:
            return dict(old, replay_suppressed=True)
    result = dict(status='blocked_before_action', confirmation_sent=False, expected=expected,
                  daily_or_maa_started=False, drones_used=False)

    def finish(reason):
        result['reason'] = reason
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    if runtime._maa_task_queue_running() is not False:
        return finish('queue_not_idle')
    before = runtime.shot('workshop_synthesis_before')
    result['before'] = before
    import cv2
    import numpy as np
    frame = cv2.imdecode(np.frombuffer(Path(before).read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR) if before else None
    if frame is None:
        return finish('current_frame_unavailable')
    height, width = frame.shape[:2]
    from workshop_visual_ocr_v1 import items as visual_items
    costs = confirmation(visual_items(runtime, before), expected, width, height)
    if costs is None:
        return finish('product_quantity_inputs_or_mood_not_verified')
    result.update(confirmation_sent=True, costs=costs, status='confirmation_sent_needs_inventory_readback')
    finish('dispatch_started_no_retry')
    runtime.tap(*costs['button'])
    # A two-second frame can be mid-animation, with only one item's mood
    # deducted. Wait for the actual obtained-material boundary, never retry.
    result['output_layer_observed'] = False
    for _ in range(6):
        runtime.wait(1)
        result['after'] = runtime.shot('workshop_synthesis_after')
        values = runtime.ocr(result['after'])
        if (any(t.strip() == '获得物资' and 800 < x < 1150 and 150 < y < 300 for t, x, y in values)
                and any(t.strip() == expected['product'] and 800 < x < 1150 and 620 < y < 720 for t, x, y in values)):
            result['output_layer_observed'] = True
            break
    return finish('exact_output_and_inventory_readback_required')
