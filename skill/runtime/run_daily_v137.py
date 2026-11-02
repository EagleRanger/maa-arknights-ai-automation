"""Append optional public Skill release notices to the original final popup."""
from pathlib import Path
from unittest.mock import patch
import run_daily_v136 as previous
from skill_update_notice_v1 import presentation_boundary, private_state_path

ENTRYPOINT = 'run_daily_v137.py --mode full'
COMPONENT = 'ARK-DAILY-SKILL-UPDATE-NOTICE-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):
        return previous.check_entry(at,packet)


def full():
    import arknights_daily_runtime_v12 as app
    root=Path(__file__).resolve().parent
    skill_root=root.parent if (root.parent/'SKILL.md').exists() else root
    # Development trees without a published release identity quietly skip.
    with presentation_boundary(app,skill_root,private_state_path(skill_root,app.BASE)), \
         patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT), patch.object(previous,'__file__',__file__):
        return previous.full()


if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())
