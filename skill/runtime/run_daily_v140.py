"""V139 plus compact stage failure notices and explicit unavailable-job filtering."""
from unittest.mock import patch
from pathlib import Path
import run_daily_v139 as previous
from event_copilot_feedback_v1 import boundary
from skill_update_notice_v1 import presentation_boundary, private_state_path
from event_evidence_retention_v1 import boundary as evidence_boundary
from event_stage_hold_v1 import boundary as hold_boundary, read_holds

ENTRYPOINT = 'run_daily_v140.py --mode full'
COMPONENT = 'ARK-DAILY-COPILOT-FEEDBACK-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    import arknights_daily_runtime_v12 as app
    root = Path(__file__).resolve().parent
    skill_root = root.parent if (root.parent/'SKILL.md').exists() else root
    with boundary(app), evidence_boundary(app), hold_boundary(app,read_holds(root)), \
         presentation_boundary(app, skill_root, private_state_path(skill_root, app.BASE)), \
         patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())
