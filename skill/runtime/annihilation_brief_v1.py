"""Recognize annihilation briefs without confusing their ENEMY icon for battle.

Scoped to the original first-clear call. Reuses its OCR; no extra polling,
queue stop, battle retry, resource refill or generic screen-click heuristic.
"""
from datetime import datetime, timedelta
import re
from unittest.mock import patch


def compact(value):
    return re.sub(r'\s+', '', str(value))


def observe(rows, evidence, started_at):
    text = compact(' '.join(str(row[0]) for row in rows))
    anchors = ('作战简报', '记录时间', '已歼灭', '标准速度耗时')
    if not all(word in text for word in anchors):
        return None
    result = dict(status='unverified', evidence=str(evidence), reason='brief_counters_unreadable')

    def number(label):
        values = set()
        for value, x, y in rows:
            token = compact(value)
            if label not in token:
                continue
            attached = re.fullmatch(re.escape(label) + r'[:：]?(\d{1,3})', token)
            if attached:
                values.add(int(attached[1]))
            for other, ox, oy in rows:
                raw = compact(other)
                if 0 < ox-x < 280 and abs(oy-y) < 40:
                    if raw == 'O' and label == '剩余防御点数':
                        raw = '0'  # Only the isolated, spatially bound zero.
                    if re.fullmatch(r'\d{1,3}', raw):
                        values.add(int(raw))
        return values.pop() if len(values) == 1 else None

    kills, leaked, defense = (number(x) for x in ('已歼灭', '已攻入敌方数', '剩余防御点数'))
    times = set(re.findall(r'20\d{2}-\d{2}-\d{2}\d{2}:\d{2}', text))
    result.update(kills=kills, leaked=leaked, defense=defense)
    if len(times) != 1:
        result['reason'] = 'brief_time_unreadable'
        return result
    try:
        recorded = datetime.strptime(times.pop(), '%Y-%m-%d%H:%M').replace(tzinfo=started_at.tzinfo)
    except ValueError:
        result['reason'] = 'brief_time_invalid'
        return result
    result['recorded_at'] = recorded.isoformat()
    if recorded < started_at.replace(second=0, microsecond=0) or recorded > datetime.now(started_at.tzinfo) + timedelta(minutes=1):
        result['reason'] = 'brief_not_current_attempt'
        return result
    if kills is None or not 0 <= kills <= 400 or defense is None or leaked is None:
        return result
    # 400 still requires the caller's exact-map best-score readback.
    result.update(status='full_kills' if kills == 400 and leaked == 0 and defense > 0 else 'incomplete',
                  reason='current_attempt_brief')
    return result


def agree(a, b):
    return bool(a and b and a.get('evidence') != b.get('evidence') and
                all(a.get(key) == b.get(key) for key in
                    ('status', 'kills', 'leaked', 'defense', 'recorded_at')))


def verify(port, stage, started_at):
    """End legacy waiting on a completed brief, never on an active queue.

    A brief is evidence, not a successful reward. After two current frames
    and an idle queue, close it once using the independently observed blank
    dismiss action. Never touch its "update" button or retry the battle.
    """
    app = port.app
    original_state, original_ocr = app.get_state, app.ocr
    observed = []

    def state(*args, **kwargs):
        captured = []
        def ocr(path, *a, **k):
            rows = original_ocr(path, *a, **k)
            brief = observe(rows, path, started_at)
            if brief is not None:
                captured.append(brief)
            return rows
        with patch.object(app, 'ocr', ocr):
            answer = original_state(*args, **kwargs)
        if captured and port.idle():
            observed.append(captured[-1])
            # Legacy verify exits only once its own MAA completion agrees.
            # Do not let the generic ENEMY match trap it for another hour.
            return 'defeat' if captured[-1]['status'] == 'incomplete' else 'reward'
        return answer

    with patch.object(app, 'get_state', state):
        outcome = app.verify_battle(stage_name=stage['name'])
    if not observed:
        return outcome
    first = observed[-1]
    row = app._RUN_SUMMARY.setdefault('annihilation_rotation', {})
    row['battle_brief'] = dict(first, stage_id=stage['stage_id'])
    if not port.idle():
        row['battle_brief']['verification'] = 'queue_not_idle'
        return 'annihilation_brief_unverified'
    app.wait(1)
    path, items = port.frame('brief_confirm')
    second = observe(items, path, started_at)
    row['battle_brief']['confirmation'] = second
    if not agree(first, second) or first['status'] == 'unverified':
        row['battle_brief']['verification'] = 'brief_unverified_or_changed'
        return 'annihilation_brief_unverified'
    row['battle_brief']['verification'] = 'two_current_frames'
    app.log('剿灭本轮作战简报：歼灭 %s/400，漏敌 %s；不把MAA结束当通关。' %
            (first['kills'], first['leaked']))
    if not port.idle():
        row['battle_brief']['dismissal'] = 'queue_changed_no_input'
        return 'annihilation_brief_unverified'
    app.tap(*app.POS_DISMISS)
    app.wait(2)
    after_path, after_items = port.frame('brief_dismissed')
    after = observe(after_items, after_path, started_at)
    row['battle_brief']['after_evidence'] = after_path
    if after is not None:
        row['battle_brief']['dismissal'] = 'unchanged_after_one_tap'
        return 'annihilation_brief_dismissal_unverified'
    page = app.get_state()
    row['battle_brief']['after_page'] = page
    if page not in {'victory', 'defeat', 'reward', 'chapter_map', 'annihilation_page', 'main_menu'}:
        row['battle_brief']['dismissal'] = 'unknown_after_one_tap'
        return 'annihilation_brief_dismissal_unverified'
    row['battle_brief']['dismissal'] = 'verified'
    return 'failed' if first['status'] == 'incomplete' else 'cleared'
