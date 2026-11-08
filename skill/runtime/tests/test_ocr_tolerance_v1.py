from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import Mock,patch
import ocr_tolerance_v1 as m
from ark_modules import vision

HOME=[('终端',1450,270),('编队',1152,510),('干员',1495,511),
      ('采购中心',1286,726),('公开招募',1510,748),('仓库',1768,892)]


def test_home_navigation_does_not_need_uid_or_exact_terminal_form():
    assert m.navigation_home(HOME)
    assert m.navigation_home([('???',1450,270)]+HOME[1:])
    assert not m.navigation_home(HOME+[('获得物资',960,350)])


def runtime():
    return SimpleNamespace(get_state=Mock(side_effect=['unknown','unknown','main_menu']),
        goto_main_menu=Mock(),_wait_unknown_navigation_page=Mock(return_value=False),
        _RUN_SUMMARY={},_RUN_MUTEX_HANDLE=True,SCRIPT_SCREENSHOT_BACKEND='adb',
        shot=Mock(side_effect=lambda tag:tag+'.png'),ocr=Mock(return_value=[('???',900,500)]),
        wait=Mock(),tap=Mock(),cleanup_after_task=Mock(),_maa_task_queue_running=lambda:False)


def test_legacy_state_consumer_recaptures_twice_without_click_or_shutdown():
    app=runtime();old=app.get_state
    with m.boundary(app):assert app.get_state()=='main_menu'
    assert old.call_count==3 and app.wait.call_count==2
    app.tap.assert_not_called();app.cleanup_after_task.assert_not_called()


def test_common_vision_waits_for_two_bad_frames_after_one_action():
    values=iter([('source',),('unknown',),('unknown',),('home',)])
    port=SimpleNamespace(now=lambda:datetime.now(timezone.utc),
        capture=lambda tag:(tag,datetime.now(timezone.utc)),ocr=lambda p:next(values),
        wait=Mock(),queue_idle=lambda:True,owns_control=lambda:True,tap=Mock())
    classifier=lambda rows:(rows[0],{})
    app=runtime()
    with m.boundary(app):
        reader=vision.Vision(port,classifier,[vision.Transition('source','home',lambda p,f:p.tap(1,2))])
        result=reader.reach('home')
    assert result.status=='succeeded' and port.tap.call_count==1


def test_navigation_unknown_budget_uses_original_ai_wait_not_cleanup():
    app=runtime()
    def ai(reason,verify):
        assert reason=='navigation_ocr_unverified_preserve_scene'
        app.ocr.return_value=HOME
        assert verify()['ok']
    app._startup_ai_wait=Mock(side_effect=ai)
    with m.boundary(app):assert app._wait_unknown_navigation_page()
    assert app._startup_ai_wait.call_count==1
    app.tap.assert_not_called();app.cleanup_after_task.assert_not_called()


def test_known_roi_uses_selected_recognizer_without_detection(tmp_path):
    from PIL import Image
    p=tmp_path/'frame.png';Image.new('RGB',(1920,1080),'black').save(p)
    engine=SimpleNamespace(text_recognizer=Mock(return_value=([('ID:12345678',.9)],.01)))
    app=SimpleNamespace(_ocr_engine=engine)
    assert m.line_items(app,p,(0,622,320,672))==[('ID:12345678',160,647)]
    assert engine.text_recognizer.call_args.args[0][0].shape[:2]==(100,640)
