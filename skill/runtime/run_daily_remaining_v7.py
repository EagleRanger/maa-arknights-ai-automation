"""Resume a sealed same-day activity remainder with the CURRENT daily runtime."""
from datetime import datetime
import argparse
import importlib
import re
import sys
from unittest.mock import patch
from daily_dispatch_v1 import ROOT, read, digest, resolve, preflight, selected_scope
from daily_activity_remainder_v1 import run_scope, reporting
from event_signin_discovery_v6 import game_day


def admit(source_id, root=ROOT, now=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', source_id):
        raise ValueError('invalid source run id')
    path = root / 'outputs/run_manifests' / (source_id + '.json')
    source = read(path)
    now = now or datetime.now().astimezone()
    started = datetime.fromisoformat(source['started_at'])
    if (source.get('run_id') != source_id or not source.get('finished_at')
            or source.get('cleanup_verified') is not True):
        raise ValueError('original owner must finish; do not start a second controller')
    if game_day(started) != game_day(now):
        raise ValueError('source belongs to a different game day')
    summary = source.get('run_summary') or {}
    if not (summary.get('event') or {}).get('name'):
        raise ValueError('source has no activity to resume')
    if ((summary.get('event') or {}).get('farm') or {}).get('status') == 'completed':
        raise ValueError('source farming already complete; do not replay it')
    # Reconcile existing same-source effects rather than treating the unchanged
    # original partial manifest as permission to farm again.
    for later in path.parent.glob('*.json'):
        if later == path:
            continue
        try:
            row = read(later)
            if not isinstance(row, dict) or not row.get('finished_at'):
                continue
            remainder = (row.get('run_summary') or {}).get('activity_remainder') or {}
            completed = (remainder.get('source_run_id') == source_id and remainder.get('farm_completed') is True
                         and game_day(datetime.fromisoformat(row['started_at'])) == game_day(now))
        except (OSError, KeyError, TypeError, ValueError, AttributeError):
            continue
        if completed:
            raise ValueError('source farming already completed by a later continuation')
    return source, digest(path)


def execute(source, source_hash, selected, checked):
    import run_daily as engine
    entry = importlib.import_module(selected['module'])
    original = engine.main
    def main(*args, **kwargs):
        # The accepted bootstrap owns run identity and rebuilds argv. Add the
        # resource switch at the final parser seam, without changing that id.
        argv = list(sys.argv)
        if '--existing-sanity-only' not in argv:
            argv.append('--existing-sanity-only')
        run_id = argv[argv.index('--run-id') + 1] if '--run-id' in argv else None
        with patch.object(sys, 'argv', argv), \
             patch.object(engine, 'run_scope', lambda port: run_scope(port, source, run_id=run_id)):
            return original(*args, **kwargs)
    with selected_scope(selected, checked), reporting(ROOT, source, source_hash), \
         patch.object(engine, 'main', main):
        return entry.full()


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--source-run-id', required=True)
    p.add_argument('--check-only', action='store_true')
    args = p.parse_args(argv)
    source, source_hash = admit(args.source_run_id)
    selected = resolve(read(ROOT / '.project-reasoning/AUTOMATION_HANDOFF.json'))
    checked = preflight(selected)
    validate = getattr(importlib.import_module(selected['module']), 'validate_current_plan', None)
    if callable(validate):
        validate()
    if args.check_only:
        print('PASS current-runtime activity remainder; no game actions; ' + selected['entrypoint'])
        return 0
    return execute(source, source_hash, selected, checked)


if __name__ == '__main__':
    raise SystemExit(main())
