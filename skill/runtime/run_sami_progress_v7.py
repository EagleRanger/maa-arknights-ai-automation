"""V6 with shared roguelike services and read-only repeated-failure evidence."""
from unittest.mock import patch
import run_sami_progress_v6 as previous
import run_sami_progress_v1 as base
from roguelike_battle_watch_v1 import boundary as watch_boundary
from roguelike_mode_v1 import rewards_until_empty

WORKFLOW = 'ARK-SAMI-PROGRESS-V7'


def main():
    import run_sami_until_deadline as sami
    old_run, old_admit = sami.run, base.admit
    current = {}
    def admit(*a, **kw):
        packet, deadline = old_admit(*a, **kw)
        current.update(packet=packet, deadline=deadline)
        return packet, deadline
    def run(*a, **kw):
        packet = current['packet']
        old_checkpoint = sami.write_checkpoint
        def checkpoint(state):
            evidence = sami.ark._RUN_SUMMARY.get('roguelike_battle_watch')
            if evidence:
                state['battle_watch'] = evidence
                if state.get('last_session'):
                    state['last_session']['battle_watch'] = evidence
            warning = sami.ark._RUN_SUMMARY.get('roguelike_battle_watch_warning')
            if warning:
                state['battle_watch_warning'] = warning
            return old_checkpoint(state)
        with watch_boundary(sami.ark, root=base.ROOT, output=base.ROOT/packet['output'], run_id=packet['run_id']), \
             patch.object(sami, 'write_checkpoint', checkpoint):
            return old_run(*a, **kw)
    with patch.object(previous, 'WORKFLOW', WORKFLOW), patch.object(base, 'admit', admit), \
         patch.object(base, 'rewards_until_empty', rewards_until_empty), patch.object(sami, 'run', run):
        return previous.main()


if __name__ == '__main__':
    raise SystemExit(main())
