"""Keep a verified current event map instead of routing through home again."""
from contextlib import contextmanager
from unittest.mock import patch
import event_navigation_recovery_v2 as navigation
import event_layout_profiles_v1 as layout
from event_map_reuse_v1 import family,nodes,page_matches,standard_frame


def prepare(app,original,event,stage):
    tl_adapter=navigation.applies(event,stage)
    codes=family(event,stage)
    general=(layout.NORMAL.fullmatch(str(stage)) and len(codes)>=3 and
             bool(event.get('section_keywords') or event.get('combat_keywords')))
    if not tl_adapter and not general:
        return original(event,stage)
    if app._maa_task_queue_running() is not False or app._maa_daily_queue_running() is not False:
        return False
    frame=app.shot('event_farm_direct_map_probe')
    rows=app.ocr(frame)
    if any('销量与影响等级' in str(t) for t,x,y in rows):
        return original(event,stage)
    if not ((tl_adapter and navigation.page_kind(rows)=='tl_map') or
            (general and stage in nodes(rows,codes) and page_matches(rows,event,codes) and standard_frame(frame))):
        return original(event,stage)
    # Same mature three-round locator, fresh target validation, no extra retry.
    opened=app._open_event_stage_detail(event,stage,tag='event_farm_direct_map',ensure_map=False)
    if not opened:return False
    path,items,_=opened
    observation=layout.inspect_frame(path,items,event,stage)
    if not observation['profile']:return False
    if not layout.PROFILES[observation['profile']].badges(path)>=.08:return False
    if not app._event_proxy_command_selected(path):
        # Let the existing handler own proxy selection; no new input path.
        return original(event,stage)
    app._RUN_SUMMARY.setdefault('event',{}).setdefault('direct_handoffs',[]).append(dict(
        stage=stage,before=str(frame),detail=str(path),from_page='verified_current_map',
        skipped='home_terminal_reentry',battle_started=False))
    app.log(f'[阶段直连] 已在本活动地图，直接确认{stage}普通三星代理；不绕回首页/终端')
    return True


@contextmanager
def boundary():
    import run_daily_v6 as installer
    original=installer.install_event_farm_detail_handoff
    def install(app):
        original(app)
        previous=app._prepare_event_farm_stage
        app._prepare_event_farm_stage=lambda event,stage:prepare(app,previous,event,stage)
        return app._prepare_event_farm_stage
    with patch.object(installer,'install_event_farm_detail_handoff',install):
        yield
