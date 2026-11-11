"""Public synthetic tests: real TL consumers; no private screenshots or device."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
import event_tl_task_rewards_v1 as old
import event_tl_task_rewards_v2 as title
import event_tl_task_rewards_v3 as navigation
import navigation_text_v1 as nav

HOME = [('终端', 1480, 230), ('采购中心', 1240, 720),
        ('公开招募', 1530, 745), ('基建', 1470, 910), ('仓库', 1770, 960)]

@pytest.mark.parametrize('y', [283, 379, 419])
def test_both_banner_rows_are_supported(y):
    rows = [('卫戍协议', 1675, 231), (old.NAME, 1694, y)]
    with title.boundary():
        assert old.token(rows, lambda text: old.NAME in text, title.BANNER_RECT) == (1694, y)

@pytest.mark.parametrize('rows', [
    [(old.NAME, 1680, 283), (old.NAME, 1694, 379)],
    [(old.NAME, 1694, 450)], [('时间啊向后', 1694, 379)],
])
def test_ambiguous_or_outside_or_wrong_activity_does_not_click(rows):
    with title.boundary():
        assert old.token(rows, lambda text: old.NAME in text, title.BANNER_RECT) is None

def test_real_claim_enters_lower_row_then_proves_empty_twice():
    lobby = [('作战结束时间 战时新闻委员会', 900, 800), (old.LABEL, 1700, 400)]
    task = [(old.LABEL, 800, 55), ('REQUIREMENT REWARDS', 900, 400)]
    data = {'tl_tasks_home': HOME + [('卫戍协议', 1675, 231), (old.NAME, 1694, 379)],
            'tl_tasks_lobby': lobby, 'tl_tasks_tab': task, 'tl_tasks_empty': task}
    frames = iter(data)
    app = SimpleNamespace(shot=lambda _: next(frames), ocr=lambda p: data[p],
        tap=Mock(), wait=lambda *_: None, _RUN_SUMMARY={}, _maa_task_queue_running=lambda: False)
    with title.boundary(), navigation.boundary(app):
        assert old.claim(app, {'name': old.NAME})
    assert [call.args for call in app.tap.call_args_list] == [(1694, 379), (1700, 400)]
    result = app._RUN_SUMMARY['event']['task_rewards']
    assert result['status'] == 'verified_no_claimable'
    assert not result.get('tl_verified_claims')

def test_enlarged_crop_uses_same_two_row_rectangle():
    app = SimpleNamespace(_RUN_SUMMARY={}, shot=Mock(return_value='fresh'), tap=Mock())
    with patch.object(nav, 'crop_read', return_value=[(old.NAME, 1694, 379)]) as crop:
        result = nav.recover(app, 'tl_tasks_home', HOME, navigation.BANNER,
            lambda _: HOME, lambda rows: navigation.scene(rows) == navigation.BANNER)
    assert (old.NAME, 1694, 379) in result
    assert crop.call_args.args[2] == title.VISIBLE_BANNER_RECT
    app.tap.assert_not_called()
