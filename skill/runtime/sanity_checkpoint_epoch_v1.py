"""A farm balance ceases to be a lower bound after a later real Copilot."""
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from unittest.mock import patch


def stamp(value):
    if not value:return None
    value=datetime.fromisoformat(value) if isinstance(value,str) else value
    return value.replace(tzinfo=timezone(timedelta(hours=8))) if value.tzinfo is None else value


def anchor_is_stale(farm_at,current_battle_at,prior_battle_lower_bound=None):
    farm=stamp(farm_at)
    known=[stamp(v) for v in (current_battle_at,prior_battle_lower_bound) if v]
    return bool(farm and known and max(known)>farm)


@contextmanager
def boundary(app,prior_battle_lower_bound=None):
    original=app._validate_stamina_ocr_against_event_checkpoint
    def validate(value,now=None):
        try:
            event=app.get_active_event(now) if now is not None else app.get_active_event()
            farm=(app._load_event_progress().get('events',{}).get(event['name'],{}) or {}).get('farm',{}) if event else {}
            if anchor_is_stale(farm.get('updated_at'),app._CURRENT_RUN_LAST_STAMINA_BATTLE_AT,prior_battle_lower_bound):
                # Value still comes from the existing live screenshot readers
                # and their consensus; no old balance supplies a new number.
                app._RUN_SUMMARY.setdefault('sanity_anchor_invalidations',[]).append(dict(
                    farm_at=farm.get('updated_at'),later_battle=str(app._CURRENT_RUN_LAST_STAMINA_BATTLE_AT or prior_battle_lower_bound)))
                return value
        except (KeyError,ValueError,TypeError):pass
        return original(value,now=now)
    with patch.object(app,'_validate_stamina_ocr_against_event_checkpoint',validate):yield
