"""Recognize the observed obsolete Bilibili client before blind startup retry.

This gate only classifies; package maintenance remains signature-checked and
separate from gameplay. No download, confirmation tap or account reset here.
"""
from contextlib import contextmanager
from unittest.mock import patch
from daily_login_supply_v1 import boundary as BASE
from daily_login_visual_v1 import StartupUnverified


def update_required(items):
    text = ''.join(''.join(str(t).split()) for t, x, y in items
                   if 400 <= x <= 1500 and 350 <= y <= 650)
    return all(s in text for s in ('当前客户端版本', '已过时', '下载最新客户端'))


@contextmanager
def boundary(app):
    with BASE(app):
        old_ocr, old_ensure = app.ocr, app.ensure_env
        active = False

        def ocr(path):
            items = old_ocr(path)
            if active and update_required(items):
                app._RUN_SUMMARY['client_update'] = dict(
                    status='required', screenshot=str(path),
                    package='com.hypergryph.arknights.bilibili',
                    message='当前客户端版本已过时，请下载最新客户端',
                    game_actions=0, automatic_uninstall=False)
                raise StartupUnverified('client_update_required')
            return items

        def ensure(*args, **kwargs):
            nonlocal active
            active = True
            try:
                return old_ensure(*args, **kwargs)
            finally:
                active = False

        with patch.object(app, 'ocr', ocr), patch.object(app, 'ensure_env', ensure):
            yield
