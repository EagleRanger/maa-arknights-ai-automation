"""Normal Sami V2 with account-scoped permanent-growth decision and feedback."""
from unittest.mock import patch
import sys
import run_sami_progress_v2 as previous
from sami_account_progress_v1 import boundary

WORKFLOW = 'ARK-SAMI-PROGRESS-V3'


def main():
    import run_sami_until_deadline as sami
    original, original_admit = sami.run, previous.base.admit
    def admit(*a, **kw):
        packet, deadline = original_admit(*a, **kw)
        prior = packet.get('previous_run')
        if prior and '--check-only' not in sys.argv:
            checkpoint = (previous.base.ROOT / prior['checkpoint']).resolve()
            checkpoint.relative_to(previous.base.ROOT / 'outputs')
            state = previous.base.read(checkpoint)
            if not (state.get('run_id') == prior['run_id'] and state.get('finished_at')
                    and state.get('cleanup_finished') is True):
                raise ValueError('previous_owned_run_not_safely_closed')
        return packet, deadline
    def run(*args, **kwargs):
        with boundary(sami, sami.ark, root=previous.base.ROOT, run_id=kwargs['run_id']):
            return original(*args, **kwargs)
    with patch.object(previous, 'WORKFLOW', WORKFLOW), patch.object(sami, 'run', run), \
            patch.object(previous.base, 'admit', admit):
        return previous.main()


if __name__ == '__main__':
    raise SystemExit(main())
