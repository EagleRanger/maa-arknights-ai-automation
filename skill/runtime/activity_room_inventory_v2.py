"""Finish the observed right-side base return; reuse sealed room details."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from unittest.mock import patch
import activity_room_inventory_v1 as old
from activity_room_navigation_v1 import partial_right_overview


def details_complete(proof):
    value=deepcopy(proof or {})
    value.update(status='all_max_verified',home_verified=True)
    return old.complete(value)


@contextmanager
def known_return(app):
    original=app.goto_main_menu
    def home():
        if app._maa_task_queue_running() is not False:return False
        p=str(app.shot('activity_room_return_identity'));items=app.ocr(p)
        if ((old.room_cards(items) or partial_right_overview(items))
            and any(str(t).strip()=='OFF' and x<400 for t,x,y in items)):
            app.tap(70,55);app.wait(1)
        return original()
    with patch.object(app,'goto_main_menu',home):yield


def observe(app,previous=None,source=None):
    # Previous details are source-hashed by the admitting packet. Returning to
    # home is an independent fact and must be observed now, never copied.
    if details_complete(previous):
        try:age=(datetime.now().astimezone()-datetime.fromisoformat(previous['observed_at'])).total_seconds()
        except (KeyError,TypeError,ValueError):age=3601
        if 0<=age<=3600 and app._maa_task_queue_running() is False:
            with known_return(app):home=app.goto_main_menu() is True
            if home:
                from daily_home_state_v1 import home_anchors
                path=str(app.shot('activity_rooms_reused_home_verified'))
                if home_anchors(app.ocr(path)):
                    value=deepcopy(previous)
                    value.update(status='all_max_verified',home_verified=True,details_reused_from=source,
                                 home_evidence=path,home_verified_at=datetime.now().astimezone().isoformat())
                    return value
            return dict(status='unverified',home_verified=False,rooms=deepcopy(previous['rooms']),reason='current_home_not_verified')
    with known_return(app):return old.observe(app)
