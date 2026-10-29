"""Map-bound milestone rewards after a saved 400-kill first clear.

No battles, queue ownership, reports or cleanup are created here. The caller
retains the daily lifecycle; this service returns its own verified result.
"""
import re
from annihilation_rotation_v1 import compact, unique_button

TIERS = {100, 200, 250, 300, 325, 350, 375, 400}


def rewards(rows):
    found = {}
    for text, x, y in rows:
        m = re.fullmatch(r'单次作战达到(100|200|250|300|325|350|375|400)(?:歼灭数|击杀数|歼敌数)', compact(text))
        if not m or x > 1000:
            continue
        tier = int(m[1])
        local = [(compact(t), tx, ty) for t, tx, ty in rows
                 if tx > 1000 and abs(ty-y) < 95]
        claimed = any(t in {'COMPLETE', '已领取', '已完成'} for t, _, _ in local)
        targets = [(int(tx), int(ty)) for t, tx, ty in local
                   if t in {'领取', '点击领取', '可领取', '领取奖励'}]
        # Disabled rows also carry faint claim text: the COMPLETE stamp wins.
        state = 'claimed' if claimed else 'claimable' if len(targets) == 1 else 'unknown'
        found[tier] = dict(state=state, target=targets[0] if state == 'claimable' else None)
    return found


def service(port, stage, *, clear_evidence=None):
    app = port.app
    row = dict(stage_id=stage['stage_id'], status='checking', views=[], claims=[])
    if not port.idle():
        return dict(row, status='blocked', reason='queue_not_idle')
    detail = port.inspect()
    row['detail'] = detail
    # No battle is permitted to repair this prerequisite. A saved result is
    # cross-checked against the exact map's current completion/milestone UI.
    fresh_complete = detail.get('status') == 'complete' and detail.get('kills') == 400
    bound = detail.get('map', {}).get('stage_id') == stage['stage_id']
    if not bound or not (fresh_complete or (clear_evidence and detail.get('progress') == dict(value=8, max=8))):
        return dict(row, status='blocked', reason='same_map_400_not_verified')
    path, items = port.frame('postclear_detail')
    panel = rewards(items)
    if not panel:
        target = unique_button(items, '作战进度')
        if not target or stage['name'] not in compact(' '.join(r[0] for r in items)):
            return dict(row, status='blocked', reason='progress_entry_not_observed', evidence=path)
        app.tap(*target); app.wait(2)
    seen, attempted = {}, set()
    for view in range(4):
        for claim in range(9):
            path, items = port.frame('postclear_rewards')
            visible = rewards(items)
            row['views'].append(dict(evidence=path, tiers=visible))
            if not visible or not port.idle():
                return dict(row, status='unverified', reason='reward_panel_unreadable_or_busy')
            seen.update(visible)
            ready = [(tier, state) for tier, state in visible.items() if state['state'] == 'claimable']
            if not ready:
                break
            tier, state = ready[0]
            if tier in attempted:
                return dict(row, status='unverified', reason='claim_did_not_change', tier=tier)
            app.wait(1)
            confirm_path, confirm_items = port.frame('postclear_claim_confirm')
            confirmed = rewards(confirm_items).get(tier)
            if confirmed != state or not port.idle():
                return dict(row, status='unverified', reason='claim_target_changed')
            attempted.add(tier)
            row['claims'].append(dict(tier=tier, before=path, confirmation=confirm_path))
            app.tap(*state['target']); app.wait(2)
            after, after_items = port.frame('postclear_claim_after')
            row['claims'][-1]['after'] = after
            if '获得物资' in compact(' '.join(r[0] for r in after_items)):
                app.dismiss_reward(); app.wait(1)
            # Next read must see the claimed stamp, never count the tap alone.
        if TIERS <= seen.keys() and all(seen[n]['state'] == 'claimed' for n in TIERS):
            row.update(status='completed', all_rewards_claimed=True, claimed_tiers=sorted(TIERS))
            app.back(); app.wait(2)
            home = port.home()
            row['home_verified'] = home
            if not home:
                row.update(status='unverified', reason='reward_exit_not_verified')
            return row
        app.swipe(950, 870, 950, 420, 750); app.wait(1)
    row.update(status='unverified', reason='not_all_eight_reward_tiers_verified', observed_tiers=sorted(seen))
    return row
