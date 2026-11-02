"""Keep current detail observations independent of first-clear and fight receipts."""
from contextlib import contextmanager
from math import isfinite
import re
from unittest.mock import patch


def configure(app, event):
    from event_availability_v12 import choose_activity_material
    from stage_sanity_cost_v2 import read_cost  # resolved after the final cost installer

    tip = app._refresh_depot_for_dynamic_333()
    choice = choose_activity_material(event, tip)
    gate = dict(event=event.get('name'), stage=None, evidence=None,
                three_stars=None, badge_ratio=None, unit_cost=None, ready=False)
    app._RUN_SUMMARY.setdefault('event', {})['farm_gate'] = gate

    def stop(reason, detail):
        gate.update(reason=reason, detail=detail)
        app.log(detail, 'WARN')
        return False

    if not choice:
        return stop('inventory_choice_unverified', '本轮库存尚未确定活动刷取目标。')
    stage = gate['stage'] = choice['stage']
    opened = app._open_event_stage_detail(event, stage, tag='new_event_farm_acceptance')
    if not opened:
        return stop('detail_unverified', f'{stage}：未确认目标详情，无法判断星级或单次理智。')
    path, items, _ = opened
    gate['evidence'] = str(path)
    try:
        ratio = app._event_normal_badges_ratio(path)
        if isfinite(ratio):
            gate.update(badge_ratio=ratio, three_stars=ratio >= .08)
    except (OSError, ValueError, TypeError):
        pass  # A missing/unreadable frame is unknown, not evidence of a lost stage.
    engine = getattr(getattr(app, '_ocr_engine', None), 'text_recognizer', None)
    try:
        reading = read_cost(path, items, engine) if engine is not None else None
    except (OSError, ValueError):
        reading = None
    cost = (reading or {}).get('unit_cost')
    if type(cost) is int and 1 <= cost <= 40:
        gate['unit_cost'] = cost
    stars = '详情已确认三星' if gate['three_stars'] else '详情未能确认三星'
    price = f'单次{cost}理智' if gate['unit_cost'] is not None else '单次理智未读出'
    observed = f'{stage}：{stars}；{price}'
    if gate['three_stars'] is not True or gate['unit_cost'] is None:
        reason = ('unit_cost_unverified' if gate['three_stars'] else
                  'badges_unverified' if gate['unit_cost'] is not None else 'badges_and_cost_unverified')
        return stop(reason, observed + '，未启动刷取。')

    gate.update(ready=True, reason='detail_verified', detail=observed + '。')
    event.update(farm_stage=stage, farm_cost=cost)
    app._RUN_SUMMARY['event']['farm_selection'] = dict(
        choice, verified=True, cost=cost, cost_reading=reading, evidence=str(path),
        inventory_sync_time=tip['depot']['sync_time'], detail_left_open_for_maa=True)
    app.log(f"{observed}；按本轮库存选择{choice['drop']}（{choice['inventory']}），保留详情给代理。")
    return True


def event_steps(app, original, event):
    before = (app._RUN_SUMMARY.get('event') or {}).get('farm_gate')
    result = original(event)
    row = app._RUN_SUMMARY.get('event') or {}
    gate = row.get('farm_gate')
    if (gate and gate is not before and gate.get('event') == event.get('name')
            and row.get('status') == 'first_clear_done_farm_target_pending' and not gate['ready']):
        row['detail'] = gate['detail']
    return result  # independent services, decisions and evidence accounting are unchanged


def popup(report, original):
    title, text, status = original(report)
    row = (report.get('run_summary') or {}).get('event') or {}
    name = row.get('name') or '本次活动'
    old = f'活动{name}：本次没有核实到已通关关卡。'
    lines = text.splitlines()
    history = (row.get('checkpoint_hint') or {}).get('historical_stages') or {}
    known = [code for code, stage in history.items() if isinstance(stage, dict)
             and ((stage.get('modes') or {}).get('normal') or {}).get('status') == 'cleared']
    codes = '、'.join(known)
    numbered = [re.fullmatch(r'(.+-)([1-9][0-9]*)', code) for code in known]
    if len(known) >= 3 and all(numbered) and len({m[1] for m in numbered}) == 1:
        nums = sorted(int(m[2]) for m in numbered)
        if nums == list(range(nums[0], nums[0] + len(nums))):
            codes = f'{numbered[0][1]}{nums[0]} 至 {numbered[0][1]}{nums[-1]}'
    progress = ('已有普通关通关记录：' + codes + '；') if known else ''
    content = [f'活动{name}：{progress}本轮没有新增首通记录。']
    gate = row.get('farm_gate') or {}
    note = gate.get('detail') if gate.get('event') == name else None
    if old in lines:
        i = lines.index(old)
        lines[i:i+1] = content + ([note] if note else [])
    elif note and not gate.get('ready') and note not in lines:
        # First clears can succeed in this run while later farming still fails.
        i = next((i for i, s in enumerate(lines) if s.startswith(f'活动{name}：')), None)
        if i is not None:
            lines.insert(i + 1, note)
    return title, '\n'.join(lines), status


@contextmanager
def boundary(app):
    import event_farm_detail_handoff_v1 as handoff
    import daily_plain_popup_v2 as presentation
    old_steps = app._run_full_event_steps
    old_summary = presentation.OLD_SUMMARY
    with patch.object(handoff, 'configure_farm_in_place', configure), \
         patch.object(app, '_run_full_event_steps', lambda event: event_steps(app, old_steps, event)), \
         patch.object(presentation, 'OLD_SUMMARY', lambda report: popup(report, old_summary)):
        yield
