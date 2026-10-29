"""Observed B105 formula-to-unassigned-picker navigation. Never confirms."""
import re


def b105(values):
    return any(re.fullmatch(r'加工站B105[0OIl1|]*', re.sub(r'\s+', '', t)) and y < 120 for t, x, y in values)


def prepare(runtime):
    evidence = []
    def read(name):
        path = runtime.shot(name); evidence.append(str(path))
        return runtime.ocr(path)
    def has(values, text):
        return any(t.strip() == text for t, x, y in values)
    if runtime._maa_task_queue_running() is not False:
        return dict(status='blocked', reason='queue_not_idle', evidence=evidence)
    values = read('workshop_picker_start')
    if b105(values) and has(values, 'FORMULA') and has(values, '加工份数'):
        runtime.tap(70, 55); runtime.wait(1)
        values = read('workshop_picker_room')
    if not b105(values) or not has(values, '进驻信息'):
        return dict(status='blocked', reason='normal_B105_not_verified', evidence=evidence)
    runtime.tap(100, 450); runtime.wait(1)
    values = read('workshop_picker_panel')
    if not b105(values) or not any('当前房间' in t and x > 1230 for t, x, y in values):
        return dict(status='blocked', reason='B105_current_worker_panel_not_verified', evidence=evidence)
    runtime.tap(1380, 210); runtime.wait(1)
    values = read('workshop_picker_list')
    if not has(values, '加工站') or not has(values, 'B105'):
        return dict(status='blocked', reason='B105_picker_not_verified', evidence=evidence)
    if not any(t.strip() == '未进驻' and x > 1500 and y < 100 for t, x, y in values):
        menu = [(x, y) for t, x, y in values if t.strip() == '全部' and 1500 < x < 1780 and y < 100]
        if len(menu) != 1:
            return dict(status='blocked', reason='unassigned_filter_control_unknown', evidence=evidence)
        runtime.tap(*menu[0]); runtime.wait(.5)
        values = read('workshop_picker_filter')
        choice = [(x, y) for t, x, y in values if t.strip() == '未进驻' and x > 1500]
        if len(choice) != 1:
            return dict(status='blocked', reason='unassigned_filter_choice_unknown', evidence=evidence)
        runtime.tap(*choice[0]); runtime.wait(1)
        values = read('workshop_picker_unassigned')
    ok = any(t.strip() == '未进驻' and x > 1500 and y < 100 for t, x, y in values)
    return dict(status='unassigned_picker_observed' if ok else 'blocked', evidence=evidence,
                confirmation_sent=False, other_workers_changed=False)
