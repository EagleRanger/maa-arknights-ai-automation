"""Sami full-research terminal: the game replaces the points with a label.

No invented zero balance. Existing partial-node checks and scanner are reused;
only the observed 43/43 terminal gains a scoped verifier and return-home path.
"""
from contextlib import contextmanager
from copy import deepcopy
import re
from unittest.mock import patch


def compact(text):
    return re.sub(r'\s+', '', str(text or ''))


def complete_text(text):
    text = compact(text)
    return '研究完成' in text and '43/43' in text and '已比较' in text


def complete_items(items, *, selected=False):
    research = any(compact(t) == '研究完成' and x >= 1500 and y <= 160 for t, x, y in items)
    # Opening a selected-node detail shifts the lower-left counter up 149 px.
    # Require one of the two observed paired layouts, not a full-page match.
    layouts = ((760, 810, 820, 870),) if selected else ((760, 810, 820, 870), (910, 960, 970, 1020))
    paired = any(
        any(re.fullmatch(r'43/43[Qq]?', compact(t)) and 90 <= x <= 350 and c0 <= y <= c1
            for t, x, y in items)
        and any(compact(t) == '已比较' and 90 <= x <= 350 and l0 <= y <= l1
                for t, x, y in items)
        for c0, c1, l0, l1 in layouts)
    upgraded = any(compact(t) == '已升级' and x >= 1500 and y >= 900 for t, x, y in items)
    return research and paired and (not selected or upgraded)


def verify_final_upgrade(before, after, progress, points):
    """Both inputs are same-node before/action and after frames; no new input."""
    if type(progress) is not int or progress != 42 or type(points) is not int or points <= 0:
        return None
    if not complete_items(after, selected=True):
        return None
    if not any(re.fullmatch(str(progress)+r'/43[Qq]?', compact(t)) and 90 <= x <= 350
               and 700 <= y <= 880 for t, x, y in before):
        return None
    if not any(compact(t) == str(points) and x >= 1740 and y <= 130 for t, x, y in before):
        return None
    if not any(compact(t) == '确认升级' and x >= 1500 and y >= 900 for t, x, y in before):
        return None
    costs = [int(compact(t)[1:]) for t, x, y in before
             if re.fullmatch(r'-\d+', compact(t)) and x >= 1500 and y >= 900]
    descriptions = lambda rows: {compact(t) for t, x, y in rows
                                 if 150 <= x <= 1400 and 990 <= y <= 1060 and len(compact(t)) >= 10}
    if len(costs) != 1 or not 0 < costs[0] <= points or not descriptions(before) & descriptions(after):
        return None
    return dict(ok=True, progress_before=progress, progress_after=43, points_before=points,
                points_after=None, points_counter_hidden=True, terminal_complete=True,
                verified_upgrade_cost=costs[0], effect_basis='same_node_cost_and_full_research_terminal')


@contextmanager
def boundary(sami):
    old_identity, old_service, old_page = sami.is_culture_page, sami.service_culture, sami.page

    def service(*args, **kwargs):
        observations = []
        def page(tag):
            value = old_page(tag)
            observations.append((tag, value))
            return value
        with patch.object(sami, 'page', page):
            result = old_service(*args, **kwargs)
            if result.get('ok') and result.get('reason') == 'culture_complete':
                terminal = next((v for tag, v in reversed(observations) if complete_items(v[1])), None)
                if terminal:
                    return dict(result, points_remaining=None, points_counter_hidden=True,
                                terminal_complete=True, terminal_screenshot=terminal[0])
            if result.get('ok') or result.get('reason') not in {
                    'culture_counter_unverified', 'upgrade_effect_unverified'}:
                return result
            if not observations or not complete_items(observations[-1][1][1]):
                return result
            candidate = deepcopy(result)
            if result['reason'] == 'upgrade_effect_unverified':
                before = next((v for tag, v in reversed(observations)
                               if tag in {'sami_culture_node_recentered', 'sami_culture_node_detail'}), None)
                after = observations[-1][1]
                proof = verify_final_upgrade(before[1] if before else [], after[1],
                                             result.get('progress'), result.get('points_remaining'))
                if proof is None:
                    return result
                proof.update(before_screenshot=before[0], after_screenshot=after[0])
                candidate['upgrades'][-1] = dict(candidate['upgrades'][-1], **proof,
                                                reason='culture_full_research_terminal_verified')
            # A second real frame is mandatory; never click another node to
            # repair the old receipt. 43/43 remains factual even if return fails.
            path, items, text = page('sami_culture_full_terminal_confirm')
            if not complete_items(items):
                return dict(candidate, ok=False, reason='culture_full_terminal_second_frame_unverified')
            home = sami.establish_sami_home()
            return dict(candidate, ok=home.get('ok') is True, progress=43,
                        points_remaining=None, points_counter_hidden=True, terminal_complete=True,
                        reason='culture_complete' if home.get('ok') else 'culture_complete_home_unverified',
                        terminal_screenshot=path, return_home=home,
                        home_confirmed_after=home.get('ok') is True)

    with patch.object(sami, 'is_culture_page', lambda text: old_identity(text) or complete_text(text)), \
         patch.object(sami, 'service_culture', service):
        yield
