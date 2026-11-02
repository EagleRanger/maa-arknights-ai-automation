"""V138 plus AI-first tutorial handoff with explicit human fallback."""
from unittest.mock import patch
import run_daily_v138 as previous
import run_daily_v133 as tutorial_owner
from tutorial_ai_handoff_v2 import boundary

ENTRYPOINT='run_daily_v139.py --mode full'
COMPONENT='ARK-DAILY-TUTORIAL-AI-V2-CANDIDATE'


def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):
        return previous.check_entry(at,packet)


def full():
    with patch.object(tutorial_owner,'tutorials',boundary), \
         patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()


if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())
