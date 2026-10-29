"""Settle known loading frames and explicitly leave an owned stale SSS task.

No next-stage/start/confirmation-for-delegation input is issued here. Battle
abandonment is allowed only after the caller proves the same saved SSS task.
"""
from contextlib import contextmanager
from unittest.mock import patch


def text(items):
    return ''.join(str(t).replace(' ', '') for t, _, _ in items)


def loading(value):
    return '正在进入' in value or ('NOWENTERING' in value.upper() and 'LT-' in value)


def saved_task_owner(items, aliases):
    battles = [(x, y) for label, x, y in items if str(label).replace(' ', '').upper() == 'INBATTLE']
    if len(battles) != 1:
        return False
    bx, by = battles[0]
    labels = [(x, y) for label, x, y in items
              if any(alias.replace(' ', '') in str(label).replace(' ', '') for alias in aliases)]
    # Bind the marker to the selected region's card, not another visible card.
    return any(abs(x-bx) < 250 and -240 < y-by < 60 for x, y in labels)


@contextmanager
def wait_for_region(app, receipt):
    original = app._sss_region_entry_confirmed

    def confirmed(value):
        if original(value):
            return True
        if not loading(value.replace(' ', '')):
            return False
        for index in range(8):
            app.wait(3)
            frame = app.shot(f'sss_loading_settle_{index}')
            receipt['screenshots'].append(str(frame))
            items = app.ocr(frame)
            fresh = text(items)
            if loading(fresh):
                continue
            receipt['settled_text'] = fresh
            if original(fresh) or app.get_state() == 'battle':
                return True
            return False
        receipt['reason'] = 'known_loading_did_not_settle'
        return False

    with patch.object(app, '_sss_region_entry_confirmed', confirmed):
        yield


def leave_saved_task(app, receipt):
    if app._maa_task_queue_running() is not False or receipt.get('saved_task_proven') is not True:
        return False
    state = app.get_state()
    receipt['resumed_page'] = state
    if state == 'battle':
        # Reuse the two controls already verified by the legacy battle recovery.
        app.tap(1800, 100)
        app.wait(2)
        app.tap(115, 80)
        app.wait(2)
        frame = app.shot('sss_owned_saved_battle_abandon')
        receipt['screenshots'].append(str(frame))
        items = app.ocr(frame)
        buttons = [(x, y) for label, x, y in items if str(label).strip() == '放弃行动' and y > 500]
        if len(buttons) != 1:
            receipt['reason'] = 'explicit_abandon_button_missing'
            return False
        app.tap(*buttons[0])
        receipt['old_battle_abandoned'] = True
        app.wait(5)
    for index in range(6):
        frame = app.shot(f'sss_saved_task_after_abandon_{index}')
        receipt['screenshots'].append(str(frame))
        value = text(app.ocr(frame))
        if app._sss_main_page_visible(value):
            receipt['old_assignment_closed'] = True
            return True
        if '结束委托' in value or '离开任务' in value:
            ok = app._leave_sss_intermediate(frame, 'sss_saved_owned_exit') is True
            receipt['old_assignment_closed'] = ok
            return ok
        # Read-only settling only: do not confirm a new round or random panel.
        if loading(value) or not value:
            app.wait(3)
            continue
        receipt['reason'] = 'saved_task_exit_page_unverified'
        return False
    return False
