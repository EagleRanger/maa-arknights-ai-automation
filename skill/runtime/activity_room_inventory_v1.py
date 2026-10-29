"""Read eight distinct activity rooms. No upgrade, assignment or collection."""
from datetime import datetime
from activity_room_navigation_v1 import actual_room, last_room_card, partial_right_overview


def room_cards(items):
    if not last_room_card(items):
        return []
    rows = [(x, y + 30) for t, x, y in items if str(t).startswith('活动室') and x > 900]
    return sorted(rows, key=lambda p: (round(p[1] / 100), p[0])) if len(set(rows)) == 8 else []


def max_room(items):
    rid = actual_room(items)
    caps = [str(t).strip() for t, x, y in items if x > 1600 and 130 < y < 240
            and str(t).strip() in ('1000', '3000', '5000')]
    return rid, caps[0] if len(caps) == 1 else None


def complete(proof):
    rooms = proof.get('rooms') or []
    return (proof.get('status') == 'all_max_verified' and proof.get('home_verified') is True
            and len(rooms) == 8 and len({r.get('room_id') for r in rooms}) == 8
            and all(r.get('room_id') and r.get('max_verified') is True and r.get('atmosphere_cap') == 5000
                    and len(r.get('evidence') or []) == 2
                    and len(set(r['evidence'])) == 2 for r in rooms))


def observe(app):
    from daily_base_333_drones_v1 import open_base
    proof = dict(status='unverified', rooms=[], evidence=[], home_verified=False,
                 observed_at=datetime.now().astimezone().isoformat(), game_mutations=0)
    def read(tag):
        if app._maa_task_queue_running() is not False:
            raise RuntimeError('queue_not_idle')
        p = str(app.shot('room_inventory_' + tag))
        proof['evidence'].append(p)
        return p, app.ocr(p)
    try:
        if app._maa_task_queue_running() is not False:
            proof['reason'] = 'queue_not_idle'
            return proof
        if not open_base(app):
            raise ValueError('base_not_reached')
        _, items = read('start')
        for n in range(4):
            if room_cards(items):
                break
            anchors = ('进驻总览', '建造模式')
            if not all(any(str(t).strip() == a for t, _, _ in items) for a in anchors):
                raise ValueError('normal_base_overview_required')
            if not any(str(t).strip() == 'OFF' and x < 400 for t, x, _ in items):
                raise ValueError('build_mode_must_be_off')
            app.swipe(1500, 850, 850, 850, 800); app.wait(1)
            _, items = read('pan_' + str(n))
        if not room_cards(items):
            raise ValueError('eight_room_grid_not_reached')
        for index in range(8):
            cards = room_cards(items)
            if len(cards) != 8:
                raise ValueError('eight_room_grid_lost')
            app.tap(*cards[index]); app.wait(1)
            p, items = read('detail_' + str(index))
            rid, cap = max_room(items)
            if not rid:
                raise ValueError('room_title_not_verified')
            if cap is None:
                info = [(x, y) for t, x, y in items if str(t).strip() == '设施信息'
                        and x < 220 and 100 < y < 330]
                if len(info) != 1:
                    raise ValueError('facility_info_not_found')
                app.tap(*info[0]); app.wait(1)
                p, items = read('info_' + str(index))
                if actual_room(items) != rid:
                    raise ValueError('room_identity_changed')
                _, cap = max_room(items)
            app.wait(0.5)
            p2, items = read('confirm_' + str(index))
            rid2, cap2 = max_room(items)
            if rid2 != rid or cap is None or cap2 != cap or p == p2:
                raise ValueError('same_room_two_frame_readback_required')
            if any(r['room_id'] == rid for r in proof['rooms']):
                raise ValueError('duplicate_room_navigation')
            proof['rooms'].append(dict(room_id=rid, atmosphere_cap=int(cap),
                                      max_verified=cap == '5000', evidence=[p, p2]))
            for n in range(2):
                if room_cards(items):
                    break
                if actual_room(items) != rid:
                    raise ValueError('unknown_room_return_page')
                app.tap(70, 55); app.wait(1)
                _, items = read(f'back_{index}_{n}')
            if partial_right_overview(items):
                app.swipe(1500, 850, 850, 850, 800); app.wait(1)
                _, items = read('return_pan_' + str(index))
        proof['status'] = ('all_max_verified' if all(r['max_verified'] for r in proof['rooms'])
                           else 'upgrades_remaining')
    except Exception as exc:
        proof['reason'] = str(exc)
    finally:
        if app._maa_task_queue_running() is False:
            proof['home_verified'] = app.goto_main_menu() is True
        if not proof['home_verified']:
            proof['status'] = 'unverified'
    return proof
