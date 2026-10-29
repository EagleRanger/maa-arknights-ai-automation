"""Diagnose incomplete weekly delegation and resume an approved first clear.

Candidate: installing the boundary performs no game action. The caller owns
the prepared runtime, queue, daily scope, report and cleanup. Only the normal
weekly step invokes this adapter after failure; no calendar reminder or map
name is needed. A successful weekly run does not trigger extra map scanning.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
from unittest.mock import patch


def compact(value):
    return re.sub(r'\s+', '', str(value or ''))


def catalog(maa_root):
    folder = Path(maa_root) / 'resource' / 'Arknights-Tile-Pos'
    data = json.loads((folder / 'overview.json').read_text(encoding='utf-8-sig'))
    result = []
    for row in data.values():
        stage = row.get('stageId', '')
        if not re.fullmatch(r'camp_(?:r_)?\d+', stage):
            continue
        tile = (folder / row.get('filename', '')).resolve()
        if not tile.is_relative_to(folder.resolve()) or not tile.is_file():
            continue
        name = compact(row.get('name'))
        if name:
            result.append(dict(stage_id=stage, name=name, level_id=row.get('levelId', ''),
                               tile=str(tile), tile_sha256=hashlib.sha256(tile.read_bytes()).hexdigest()))
    return result


def observe(items, maps, evidence):
    """Only map-specific best kill progress counts, never a weekly 1800 cap.

    OCR observations use runtime's 1920x1080 coordinate convention. Separate
    label/value tokens are supported. A bare 400 or a victory label is not a
    first-clear proof. Ambiguous maps/counters remain unknown.
    """
    text = compact(' '.join(str(row[0]) for row in items))
    matches = {row['stage_id']: row for row in maps if row['name'] in text}
    detail = ('开始行动' in text or '全权委托' in text)
    if len(matches) != 1 or not detail:
        return dict(status='unknown', reason='map_detail_not_unique', evidence=evidence)
    stage = next(iter(matches.values()))
    values = set()
    labels = ('最高歼敌数', '最高歼灭数', '最高击杀数', '最高纪录', '最高记录', '作战进度')
    for value, x, y in items:
        if not any(label in compact(value) for label in labels):
            continue
        nearby = [(t, tx, ty) for t, tx, ty in items
                  if abs(ty - y) <= 65 and abs(tx - x) <= 430]
        local = compact(' '.join(str(t) for t, _, _ in sorted(nearby, key=lambda r: (r[2], r[1]))))
        fractions = re.findall(r'(?<!\d)(\d{1,3})/400(?!\d)', local)
        if fractions:
            values.update(int(n) for n in fractions if 0 <= int(n) <= 400)
        else:
            attached = re.findall(r'(?:最高歼敌数|最高歼灭数|最高击杀数|最高纪录|最高记录)[:：]?(\d{1,3})(?!\d|/)', compact(value))
            values.update(int(n) for n in attached if 0 <= int(n) <= 400)
            # Standalone number must share a labeled row, not be the cost,
            # weekly reward, or the denominator of an unparsed fraction.
            for t, tx, ty in nearby:
                if abs(ty-y) <= 35 and re.fullmatch(r'\d{1,3}', compact(t)):
                    n = int(compact(t))
                    if 0 <= n <= 400:
                        values.add(n)
    if len(values) != 1:
        return dict(status='unknown', reason='best_kills_unreadable', map=stage, evidence=evidence)
    kills = values.pop()
    return dict(status='complete' if kills == 400 else 'first_clear_required',
                map=stage, kills=kills, evidence=evidence)


def agree(first, second):
    return (first.get('status') != 'unknown' and second.get('status') == first.get('status')
            and first.get('map', {}).get('stage_id') == second.get('map', {}).get('stage_id')
            and first.get('kills') == second.get('kills')
            and bool(first.get('evidence')) and bool(second.get('evidence'))
            and first['evidence'] != second['evidence'])


def job_matches(job, stage):
    # Chinese titles are NOT normalized to an empty ASCII key. Geometry must
    # identify exactly the observed map, irrespective of document title.
    actual = str(job.get('stage_name', '')).strip().lower()
    aliases = {stage['stage_id'].lower(), stage.get('level_id', '').lower(),
               'level_' + stage['stage_id'].lower()}
    return bool(actual) and actual in aliases


def unique_button(items, label):
    rows = [(int(x), int(y)) for text, x, y in items if compact(text) == label]
    return rows[0] if len(rows) == 1 else None


def terminal_card(image_path, maa_root):
    """Reuse MAA's actual template/ROI/threshold; never a memorized click."""
    import cv2
    import numpy as np
    root = Path(maa_root) / 'resource'
    tasks = json.loads((root/'tasks/tasks.json').read_text(encoding='utf-8-sig'))
    rule = tasks['Annihilation']
    images = list((root/'template').rglob(rule['template']))
    if len(images) != 1:
        return None
    frame = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    template = cv2.imdecode(np.fromfile(str(images[0]), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or template is None:
        return None
    x, y, w, h = rule['roi']
    crop = cv2.resize(frame, (1280, 720))[y:y+h, x:x+w]
    if crop.shape[0] < template.shape[0] or crop.shape[1] < template.shape[1]:
        return None
    gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    lo, hi = rule.get('maskRange', [0, 255])
    mask = cv2.inRange(gray, lo, hi)
    scores = cv2.matchTemplate(crop, template, cv2.TM_CCORR_NORMED, mask=mask)
    scores = np.nan_to_num(scores, nan=-1, posinf=-1, neginf=-1)
    _, score, _, point = cv2.minMaxLoc(scores)
    if score < rule.get('templThreshold', .9):
        return None
    return (int((x+point[0]+template.shape[1]/2)*1.5),
            int((y+point[1]+template.shape[0]/2)*1.5))


class RuntimePort:
    def __init__(self, app):
        self.app = app
        self.maps = catalog(app._maa_install_root())

    def idle(self):
        return self.app._maa_task_queue_running() is False

    def frame(self, tag):
        for attempt in range(3):
            path = self.app.shot('annihilation_rotation_' + tag + '_' + str(attempt))
            items = self.app.ocr(path)
            if items:
                return str(path), items
            self.app.wait(1)  # Black/loading frame: recapture, never tap it.
        return str(path), items

    def inspect(self):
        if not self.idle():
            return dict(status='unknown', reason='terminal_or_queue_unavailable')
        # A stopped GUI queue is not proof that the game left a battle.
        # Observe first; the ordinary owner's recovery/tail handles unknown UI.
        state = self.app.get_state()
        if state not in {'main_menu', 'terminal_list', 'routine_tasks',
                         'annihilation_page', 'annihilation_reward_overlay',
                         'chapter_map', 'victory', 'defeat', 'formation'}:
            return dict(status='unknown', reason='unsafe_or_unknown_page', page=state)
        if not self.app.goto_terminal_main():
            return dict(status='unknown', reason='terminal_unavailable')
        path, items = self.frame('terminal')
        card = terminal_card(path, self.app._maa_install_root())
        if card:
            self.app.tap(*card)
            self.app.wait(2)
        else:
            # The weekly card disappears at the cap. Reuse the established
            # routine-tab path, then require an observed entry, not coordinates.
            self.app.tap(*self.app.POS_TERMINAL_ROUTINE)
            self.app.wait(2)
        for index in range(4):
            path, items = self.frame('detail_' + str(index))
            first = observe(items, self.maps, path)
            if first['status'] != 'unknown':
                self.app.wait(1)
                second_path, second_items = self.frame('confirm')
                second = observe(second_items, self.maps, second_path)
                if agree(first, second):
                    second['before_evidence'] = first['evidence']
                    return second
                return dict(status='unknown', reason='map_frames_disagree', evidence=[path, second_path])
            if first.get('map'):
                return first  # Exact detail but unreadable kills: no guessed tap.
            target = unique_button(items, '剿灭作战') or unique_button(items, '剿灭委托')
            if not target:
                return first
            self.app.tap(*target)
            self.app.wait(2)
        return dict(status='unknown', reason='navigation_did_not_converge', evidence=path)

    def find_job(self, stage):
        # Reuse existing local-first lookup, network retry and creator ranking;
        # only narrow its matcher to this map's reversible internal aliases.
        with patch.object(self.app, '_copilot_matches_stage',
                          lambda content, *_: job_matches(content, stage)):
            path = self.app.get_copilot_json(stage['stage_id'], stage['name'],
                                            require_sandbox_choices=False)
        if not path:
            return None
        job = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        compatible, reason = self.app._copilot_auto_compatibility(job)
        if not job_matches(job, stage) or not job.get('actions') or not compatible:
            raise ValueError('copilot_mismatch_or_incompatible: ' + str(reason))
        return dict(path=str(path), sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                    doc=job.get('doc', {}), stage_id=stage['stage_id'])

    def enter_formation(self, stage):
        if not self.idle():
            return False
        path, items = self.frame('before_formation')
        current = observe(items, self.maps, path)
        if (current.get('map', {}).get('stage_id') != stage['stage_id']
                or current.get('status') != 'first_clear_required'):
            return False
        target = unique_button(items, '开始行动')
        if not target:
            return False
        self.app.tap(*target)
        self.app.wait(2)
        path, items = self.frame('formation')
        # A medicine prompt is not formation; never click it here.
        return self.app._is_formation_page_text(' '.join(str(x[0]) for x in items)) is True

    def approved_job(self, stage):
        root = Path(self.app.BASE)
        handoff = json.loads((root/'.project-reasoning/AUTOMATION_HANDOFF.json').read_text(encoding='utf-8-sig'))
        approved = (handoff.get('current_weekly_annihilation_intake') or {}).get('approved_jobs', {})
        row = approved.get(stage['stage_id'])
        if not row:
            return None
        path = Path(row['path'])
        path = path if path.is_absolute() else root/path
        payload = path.read_bytes()
        job = json.loads(payload.decode('utf-8-sig'))
        compatible, _ = self.app._copilot_auto_compatibility(job)
        if (row.get('status') != 'approved' or not row.get('source')
                or hashlib.sha256(payload).hexdigest().lower() != str(row.get('sha256','')).lower()
                or not job_matches(job, stage) or not job.get('actions') or not compatible):
            raise ValueError('approved_copilot_changed_or_incompatible')
        return dict(row, path=str(path), doc=job.get('doc',{}), stage_id=stage['stage_id'])

    def report(self, summary):
        # Reuse the existing project outbox, including its delivery receipt.
        # An unchanged map/problem/job within one week does not wake AI again
        # merely because the next daily has a new run ID or screenshot path.
        from event_page_guard_v1 import publish_page_attention
        before = summary.get('before') or {}
        stage = before.get('map') or {}
        candidate = summary.get('job') or summary.get('candidate_job') or {}
        identity = [self.app._annihilation_week_key(), stage.get('stage_id'),
                    summary.get('status'), before.get('kills'), candidate.get('sha256'),
                    summary.get('battle_result'), summary.get('reason')]
        key = 'annihilation-' + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:20]
        path = publish_page_attention(self.app.OUTPUT_DIR, key, stage.get('name',''),
            summary['status'], [summary.copy()], summary.get('battle_result'))
        packet = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        summary['attention_packet'] = path
        summary['delivery_status'] = packet.get('delivery_status', 'pending')
        self.app._RUN_SUMMARY['page_attention'] = dict(path=path, reason=summary['status'],
            status='delivered' if packet.get('delivery_status') == 'delivered' else 'pending')
        self.app.log('剿灭异常已自动取证/检索，沿原反馈通道处理: ' + path, 'WARN')

    def battle(self, job, stage):
        if not self.app.run_maa_copilot(job['path']):
            return 'start_failed'
        return self.app.verify_battle(stage_name=stage['name'])

    def home(self):
        return self.idle() and self.app.goto_main_menu() is True


def first_clear(port, summary, *, before=None, job=None):
    """One project-approved first-clear attempt, not an open-ended strategy loop."""
    before = before or port.inspect()
    summary.update(before=before)
    if before['status'] == 'unknown':
        summary.update(status='unknown', reason=before.get('reason'))
        return False
    if before['status'] == 'complete':
        summary.update(status='already_complete', first_clear_verified=True)
        return port.home()
    stage = before['map']
    job = job or port.approved_job(stage)
    if not job:
        summary.update(status='project_job_review_required', first_clear_verified=False)
        return False
    summary['job'] = job
    if not port.enter_formation(stage):
        summary.update(status='formation_unverified', first_clear_verified=False)
        return False
    result = port.battle(job, stage)
    summary['battle_result'] = result
    if result not in ('perfect', 'cleared') or not port.idle():
        summary.update(status='battle_unverified', first_clear_verified=False)
        return False
    after = port.inspect()
    summary['after'] = after
    ok = (after['status'] == 'complete'
          and after.get('map', {}).get('stage_id') == stage['stage_id']
          and after.get('kills') == 400)
    summary.update(status='completed' if ok else 'first_clear_unverified', first_clear_verified=ok)
    if ok and not port.home():
        summary['status'] = 'first_clear_verified_home_unverified'
        return False
    return ok


@contextmanager
def boundary(app, port_factory=RuntimePort):
    original = app._run_full_annihilation_step

    def weekly(force=False, times=None):
        outcome = original(force=force, times=times)
        # Preserve the ordinary weekly route. A successful or skipped run has
        # no added screenshots, lookup requests, AI messages or first-clear.
        if outcome is True or not app._plan_allows('annihilation'):
            return outcome
        summary = app._RUN_SUMMARY.setdefault('annihilation_rotation', {})
        summary['weekly_before'] = dict(app._RUN_SUMMARY.get('annihilation') or {})
        port = None
        try:
            port = port_factory(app)
            if not port.idle():
                summary.update(status='queue_still_running', first_clear_verified=False)
                port.report(summary)
                return False
            before = port.inspect()
            summary['before'] = before
            if before['status'] != 'first_clear_required':
                summary.update(status='weekly_failure_not_proven_new_map', first_clear_verified=False)
                port.report(summary)
                return False
            stage = before['map']
            job = port.approved_job(stage)
            if not job:
                summary['candidate_job'] = port.find_job(stage)
                summary.update(status='new_map_copilot_review_required' if summary['candidate_job'] else
                               'new_map_no_matching_copilot', first_clear_verified=False)
                port.report(summary)
                return False
            if not first_clear(port, summary, before=before, job=job):
                port.report(summary)
                return False
            # Resume only the remaining weekly delegation, not the whole day.
            result = original(force=True, times=times)
            summary['weekly_resumed'] = result is True
            if result is not True:
                summary['status'] = 'first_clear_verified_weekly_incomplete'
                port.report(summary)
            return result
        except Exception as exc:
            summary.update(status='first_clear_verified_weekly_error' if summary.get('first_clear_verified')
                           else 'technical_error', reason=str(exc))
            summary.setdefault('first_clear_verified', False)
            try:
                if port is not None:
                    port.report(summary)
                else:
                    app._event_page_attention('annihilation_intake_unavailable', observations=[summary.copy()])
            except Exception as feedback_error:
                summary['feedback_error'] = str(feedback_error)
                summary['delivery_status'] = 'pending'
            return False

    with patch.object(app, '_run_full_annihilation_step', weekly):
        yield
