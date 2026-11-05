"""Account-aware V3 plus the exact enemy-details interruption recovery hook."""
from contextlib import contextmanager
from unittest.mock import patch
import run_sami_progress_v3 as previous
from sami_enemy_details_v1 import boundary as enemy_boundary

WORKFLOW='ARK-SAMI-PROGRESS-V4'


def main():
    original=previous.boundary
    @contextmanager
    def final_boundary(sami,app,**kw):
        # Installed at the final runtime consumer, after shared service wrappers.
        with original(sami,app,**kw) as state, enemy_boundary(app):
            yield state
    with patch.object(previous,'WORKFLOW',WORKFLOW), patch.object(previous,'boundary',final_boundary):
        return previous.main()


if __name__=='__main__': raise SystemExit(main())
