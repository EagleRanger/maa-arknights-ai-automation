"""Discover announcements only in visible HWNDs owned by exact portable MAA."""
from contextlib import contextmanager
from unittest.mock import patch
from maa_window_handle_v2 import inventory


def candidates(rows):
    return [r for r in rows if r['visible'] and r['enabled'] and r['width']>=200 and r['height']>=100
        and (r['title']=='公告' or r['title'].startswith('MAA'))]


def find(app,ua,fallback=None):
    for row in candidates(inventory(app.MAA_PATH)):
        window=ua.ControlFromHandle(row['hwnd'])
        if int(window.ProcessId)!=row['pid']:continue
        if app._is_maa_announcement_window(window):return window
    return None


@contextmanager
def boundary(app):
    with patch.object(app,'_find_maa_announcement_window',lambda ua,fallback=None:find(app,ua,fallback)):
        yield
