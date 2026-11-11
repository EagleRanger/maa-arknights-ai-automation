"""Formation-only goal navigation using existing SSS navigation/MAA bridge.

No delegate cards, commission termination, deployment or battle dispatch.
"""
from unittest.mock import patch

FORMATION = ('快捷编队', '首批作战小队选任', '阵容确认', 'FORMATION')


def prepare(app, region, job):
    valid, reason = app._validate_sss_formation_profile(region, job)
    pages, actions = [], []
    result = dict(status='needs_ai', formation_confirmed=False, battle_invoked=False,
                  pages=pages, actions=actions)
    if not valid:
        return dict(result, reason=reason)
    entered = False
    last = None
    unchanged = 0
    for index in range(18):
        if app._maa_task_queue_running() is not False:
            return dict(result, reason='maa_busy_no_extra_input')
        path = app.shot('receiver_sss_prepare_' + str(index))
        items = app.ocr(path)
        text = ' '.join(str(r[0]) for r in items)
        pages.append(dict(screenshot=str(path), text=text))
        signature = ''.join(text.split())
        unchanged = unchanged + 1 if signature == last else 0
        last = signature
        if any(word in text for word in FORMATION):
            ok = app._configure_sss_formation(region, job) is True
            return dict(result, status='formation_confirmed' if ok else 'needs_ai',
                        formation_confirmed=ok, reason='existing_maa_formation_bridge_returned')
        if '开始部署' in text:
            return dict(result, reason='already_at_deploy_verify_existing_lineup_no_battle')
        if '暂停任务' in text or '结束委托' in text:
            return dict(result, reason='existing_commission_preserved_no_abort')
        if unchanged >= 3:
            return dict(result, reason='preparation_page_unchanged')

        def click(point, why):
            if not point or app._maa_task_queue_running() is not False:
                return False
            app.tap(*point)
            actions.append(dict(point=list(point), reason=why))
            app.wait(2)
            return True

        if '选择定向导能元件' in text or 'ENERGYCONDUCTION' in text:
            buff = job.get('buff')
            point = app.find_text(items, buff, exact=True) if isinstance(buff, str) and buff else None
            if not click(point, 'job_required_buff'):
                return dict(result, reason='required_buff_not_found')
            fresh = app.shot('receiver_sss_buff_selected')
            current = app.ocr(fresh)
            pages.append(dict(screenshot=str(fresh)))
            point = app.find_text(current, '确认选择') or app.find_text(current, '确认')
            if not click(point, 'confirm_selected_buff'):
                return dict(result, reason='buff_confirmation_not_found')
        elif '请确认战术装备配置' in text or '装备确认' in text:
            equipment = job.get('equipment')
            if (not isinstance(equipment, list) or len(equipment) != 8 or
                    any(str(choice).strip().upper() not in ('A', 'B') for choice in equipment)):
                return dict(result, reason='job_equipment_array_required')
            # Same accepted eight-card coordinates as run_sss_copilot. Raw
            # screenshot geometry is 1920x1080 by the common target binding.
            for number, choice in enumerate(equipment):
                x = int(1920 * ((.13, .38, .63, .88)[number % 4] +
                    (-.058 if str(choice).strip().upper() == 'A' else .058)))
                y = int(1080 * (.216, .535)[number // 4])
                if not click((x, y), 'job_required_equipment'):
                    return dict(result, reason='maa_busy_during_equipment')
            fresh = app.shot('receiver_sss_equipment_selected')
            current = app.ocr(fresh)
            pages.append(dict(screenshot=str(fresh)))
            if not click(app.find_text(current, '装备确认'), 'confirm_equipment'):
                return dict(result, reason='equipment_confirmation_not_found')
        elif app._sss_region_entry_confirmed(text):
            if not click(app.find_text(items, '开始保全作战', exact=True), 'enter_preparation_only'):
                return dict(result, reason='preparation_entry_not_found')
        elif app._sss_main_page_visible(text):
            if app.select_sss_region(region) is not True:
                return dict(result, reason='region_not_reached')
            actions.append(dict(reason='existing_select_sss_region', region=region))
            entered = True
        elif not entered:
            # The full-period navigator normally ends old commissions. This
            # goal only prepares a lineup, so suppress that destructive branch
            # before entering it, including a resumed page reached from home.
            with patch.object(app, '_leave_sss_intermediate', return_value=False, create=True):
                reached = app.goto_sss_page()
            entered = True
            actions.append(dict(reason='existing_goto_sss_page'))
            if reached is not True:
                # Re-observe once: an existing setup page can be continued by
                # this goal; a commission/deploy page is retained above.
                continue
        else:
            return dict(result, reason='unrecognised_preparation_page_no_blind_input')
    return dict(result, reason='preparation_budget_reached')
