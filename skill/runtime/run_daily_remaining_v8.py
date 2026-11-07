"""Resume a sealed startup-navigation skip through the current daily planner.

Existing event-specific remainders keep V7. If no stamina domain was entered,
resume those unstarted domains using the original planner and its same-day
completion caches, followed by the existing post-fight tail. No refills.
"""
from unittest.mock import patch
import run_daily_remaining_v7 as previous
from run_daily import run_scope as unstarted_scope
from daily_signin_recovery_v2 import NAVIGATION_REASONS


def admit(source_id, root=previous.ROOT, now=None):
    try:
        return previous.admit(source_id, root, now)
    except ValueError as exc:
        # V7 already checked identity, sealed cleanup and the same game day.
        if str(exc) != 'source has no activity to resume':
            raise
    path = root / 'outputs/run_manifests' / (source_id + '.json')
    source = previous.read(path)
    summary = source.get('run_summary') or {}
    if (source.get('business_complete') is True
            or (summary.get('page_attention') or {}).get('reason') not in NAVIGATION_REASONS
            or (summary.get('startup_ai_cooperation') or {}).get('status') != 'resumed'
            or summary.get('final_daily_completed') is not True
            or any(summary.get(key) for key in ('event', 'annihilation', 'flow_target',
                                               'remaining_sanity_use', 'terminal_event_detection'))):
        raise ValueError('not a sealed startup-only navigation skip; reconcile actual effects first')
    return source, previous.digest(path)


def run_scope(app, source):
    if (source.get('run_summary') or {}).get('event'):
        return previous.run_scope(app, source)
    app._DAILY_EXISTING_SANITY_ONLY = True
    app._RUN_SUMMARY['startup_remainder'] = dict(
        source_run_id=source['run_id'], scope='unstarted_pre_tail_domains',
        prior_effects='preserved_in_source_not_credited_again',
        policy='original_priorities_and_same_day_caches_then_post_fight_tail')
    return unstarted_scope(app)


def main(argv=None):
    # Reuse the selected-runtime bootstrap and the verified resource/identity seam.
    old_admit, old_scope = previous.admit, previous.run_scope
    def checked(source_id, root=previous.ROOT, now=None):
        with patch.object(previous, 'admit', old_admit):
            return admit(source_id, root, now)
    def scoped(app, source):
        with patch.object(previous, 'run_scope', old_scope):
            return run_scope(app, source)
    with patch.object(previous, 'admit', checked), patch.object(previous, 'run_scope', scoped):
        return previous.main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
