"""Three observation-led recovery rounds, without replaying a battle.

V2 also drains explicit battle-result pages within the same three rounds.
Result acknowledgement is navigation, never proof of victory.
The engine is reusable; current visual/action adapter is only the observed TL
normal map, its sales explanation, and activity lobby. Other events retain
their existing adapters. A transparent background label is not a foreground
map. No Start button, purchases, resource use, or input while MAA is running.
"""
from contextlib import contextmanager
import re
from unittest.mock import patch

MAX_RECOVERY_ROUNDS = 3


def page_kind(rows):
    text = ''.join(str(t).replace(' ', '') for t, _, _ in rows)
    # Real 2026-11-01 TL-10 failure has both result titles plus EXP/refund.
    # Refund takes precedence; never reinterpret this as victory or a map.
    if ('行动结束' in text and 'MISSIONRESULTS' in text.upper()
            and ('EXP' in text.upper() or '理智返还' in text)):
        return 'failed_result' if '理智返还' in text else 'battle_result'
    # Foreground identities MUST precede the map labels visible behind them.
    if all(s in text for s in ('销量与影响等级', '累计销量', '部署费用降低', '效果')):
        return 'tl_sales_info'
    if all(s in text for s in ('战时新闻委员会', '残照终尽', '作战结束时间', '晨曦所见证的')):
        return 'tl_lobby'
    if re.search(r'TL-(?:EX-|TR-|ST-)?\d+', text):
        if any(s in text for s in ('开始行动', '代理指挥', '推荐平均等级', '开始突袭')):
            return 'tl_detail'
        if ('残照终尽' in text or '累计销量' in text) and 'OPERATION' in text:
            return 'tl_map'
    return 'unknown'


def applies(event, stage):
    return ((event or {}).get('stage_prefix') == 'TL'
            and re.fullmatch(r'TL-(?:ST-|TR-)?\d+', str(stage)) is not None)


def observe(app, tag):
    frame = app.shot(tag)
    rows = app.ocr(frame)
    text = ' '.join(str(t) for t, _, _ in rows)
    return frame, rows, text


def busy(app):
    return app._maa_task_queue_running() or app._maa_daily_queue_running()


def target_confirmed(app, obs, stage):
    return (page_kind(obs[1]) not in ('failed_result', 'battle_result')
            and app._event_stage_detail_confirmed(obs[2], stage, obs[1]))


def locate_visible(app, original, stage, event=None):
    if not applies(event, stage):
        return original(stage, event=event)
    if busy(app):
        return None, [], None
    frame, rows, _ = observe(app, 'event_recovery_visible_' + stage)
    pos = app._event_stage_position(rows, stage)
    if page_kind(rows) == 'tl_map' and pos and app._event_stage_marker_reliable(pos):
        return frame, rows, pos
    # Retain the established map scanner only when the node is not visible.
    # Its result will be reclassified by open_detail before any node click.
    return original(stage, event=event)


def open_detail(app, original, event, stage, *, tag='event_detail', ensure_map=True):
    if not applies(event, stage):
        return original(event, stage, tag=tag, ensure_map=ensure_map)
    receipt = dict(stage=stage, max_rounds=MAX_RECOVERY_ROUNDS, rounds=[],
                   status='recovering', battle_retry=False)
    app._RUN_SUMMARY.setdefault('event', {}).setdefault('navigation_recovery', []).append(receipt)
    # No blind Back on a failed click: it previously left the real map for the
    # lobby. Each round starts from a fresh screenshot, not the last position.
    for number in range(1, MAX_RECOVERY_ROUNDS + 1):
        if busy(app):
            receipt['status'] = 'active_maa_hands_off'
            return None
        obs = observe(app, f'{tag}_{stage}_recover_{number}')
        row = dict(number=number, before=str(obs[0]), kind=page_kind(obs[1]), actions=[])
        receipt['rounds'].append(row)

        def refresh(label):
            value = observe(app, f'{tag}_{stage}_recover_{number}_{label}')
            row['after'] = str(value[0])
            row['after_kind'] = page_kind(value[1])
            return value

        def click(point, action):
            if busy(app):
                return False
            if app.tap(*point) is False:
                row['input_rejected'] = True
                return False
            row['actions'].append(dict(action=action, point=list(point)))
            app.wait(2)
            return True

        if target_confirmed(app, obs, stage):
            receipt.update(status='target_detail_verified', evidence=str(obs[0]))
            return obs
        kind = page_kind(obs[1])
        if kind in ('failed_result', 'battle_result'):
            receipt.setdefault('settlement_frames', []).append(dict(
                screenshot=str(obs[0]), observed_outcome=(
                    'failed' if kind == 'failed_result' else 'not_inferred')))
            # Reuse the already accepted result-page acknowledgement point.
            # Reobserve afterwards; if still on result, the next round retries
            # only this acknowledgement, never Start or the battle itself.
            if not click(app.POS_DISMISS, 'acknowledge_battle_result'):
                continue
            obs = refresh('result_acknowledged')
            kind = page_kind(obs[1])
        if kind == 'tl_sales_info':
            # This exact dismissal was observed at 16:51:50 -> 16:51:56.
            # It only dismisses the info layer; a NEW frame must confirm map
            # before the following node input. It does not count as opening it.
            point = app._event_stage_position(obs[1], stage)
            if point and app._event_stage_marker_reliable(point):
                if not click(point, 'dismiss_sales_information'):
                    continue
                obs = refresh('info_closed')
                kind = page_kind(obs[1])
        if kind == 'tl_lobby':
            point = app.find_text(obs[1], '残照终尽', exact=True)
            if point and click(point, 'return_to_normal_map'):
                obs = refresh('map')
                kind = page_kind(obs[1])
        if kind == 'unknown' and ensure_map and app.get_state() in ('main_menu', 'terminal_list', 'chapter_overview'):
            if not busy(app) and app.goto_event_map(event):
                row['actions'].append(dict(action='known_page_return_to_event_map'))
                obs = refresh('known_page_map')
                kind = page_kind(obs[1])
        if kind == 'tl_detail' and not target_confirmed(app, obs, stage):
            if not busy(app):
                app.back()
                row['actions'].append(dict(action='leave_other_stage_detail'))
                app.wait(2)
                obs = refresh('other_detail_closed')
                kind = page_kind(obs[1])
        if kind == 'tl_map':
            point = app._event_stage_position(obs[1], stage)
            if not point or not app._event_stage_marker_reliable(point):
                frame, rows, point = app._locate_event_stage(stage, event=event)
                if frame:
                    obs = (frame, rows, ' '.join(str(t) for t, _, _ in rows))
                    kind = page_kind(rows)
            if kind == 'tl_map' and point and app._event_stage_marker_reliable(point):
                if click(point, 'open_target_detail'):
                    obs = refresh('target')
        if target_confirmed(app, obs, stage):
            receipt.update(status='target_detail_verified', evidence=str(obs[0]))
            app.log(f'[导航恢复] {stage}第{number}轮已确认目标详情，接回原流程；未重打战斗')
            return obs
        row['status'] = 'not_yet_at_target'
        app.log(f'[导航恢复] {stage}第{number}/{MAX_RECOVERY_ROUNDS}轮未回目标，重新观察；不判战败', 'WARN')
        app.wait(2)
    receipt['status'] = 'recovery_exhausted'
    app.log(f'[导航恢复] {stage}连续{MAX_RECOVERY_ROUNDS}轮仍未确认目标，保留现场并交原反馈通道', 'ERROR')
    # Signal the existing caller now, so its legacy outer navigation loop does
    # not multiply three rounds by a second retry budget.
    reason = ('post_battle_detail_unverified' if tag.startswith('event_verify_detail')
              else 'event_navigation_recovery_exhausted')
    app._event_page_attention(reason, stage, observations=[
        dict(screenshot=str(obs[0]), ocr=obs[2], recovery=receipt)])
    return None


@contextmanager
def boundary(app):
    import event_attention_dispatch as dispatch
    old_open = app._open_event_stage_detail
    old_locate = app._locate_event_stage
    old_state = app.get_state

    def state():
        value = old_state()
        if value != 'unknown':
            return value
        obs = observe(app, 'event_recovery_page_identity')
        if page_kind(obs[1]) in ('tl_lobby', 'tl_map'):
            # Existing chapter_map route uses the visible top Home, then the
            # explicit Home label. Also consumed by mode_daily cold-start.
            return 'chapter_map'
        return value

    def opened(event, display_name, *, tag='event_detail', ensure_map=True):
        return open_detail(app, old_open, event, display_name, tag=tag, ensure_map=ensure_map)

    def located(display_name, event=None):
        return locate_visible(app, old_locate, display_name, event)

    with patch.dict(dispatch.REASON_LABELS, {'event_navigation_recovery_exhausted': '页面偏离后已尝试恢复三轮，仍未回到目标关卡'}), \
         patch.object(app, '_open_event_stage_detail', opened), \
         patch.object(app, '_locate_event_stage', located), patch.object(app, 'get_state', state):
        yield
