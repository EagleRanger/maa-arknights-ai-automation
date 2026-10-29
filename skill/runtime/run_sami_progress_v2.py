"""Normal progress V1 composition + retained controller / AI recheck protocol.

Candidate only: a NEW current V2 handoff is required. No expired-run restart.
"""
from unittest.mock import patch
import run_sami_progress_v1 as base
from sami_cooperation_v1 import boundary

WORKFLOW = 'ARK-SAMI-PROGRESS-V2'


def main():
    # Reuse the V1 environment/configuration/deadline composition verbatim.
    # Install at sami.run, AFTER all its V1 wrappers have been installed.
    import run_sami_until_deadline as sami
    original_admit, original_run = base.admit, sami.run
    current = {}

    def admit(*args, **kwargs):
        packet, deadline = original_admit(*args, **kwargs)
        current.update(packet=packet, deadline=deadline)
        return packet, deadline

    def run(*args, **kwargs):
        with boundary(sami, sami.ark, packet=current['packet'], deadline=current['deadline'],
                      output=base.ROOT / current['packet']['output'],
                      event_output=base.ROOT / 'outputs') as control:
            result = original_run(*args, **kwargs)
            # The legacy supervisor catches ControlExit as a generic exception.
            # A verified requested/deadline close is not a technical crash.
            if control.exit_reason and control.state.get('cleanup_finished') is True:
                return 0
            return result

    with patch.object(base, 'WORKFLOW', WORKFLOW), patch.object(base, 'admit', admit), \
            patch.object(sami, 'run', run):
        return base.main()


if __name__ == '__main__':
    raise SystemExit(main())
