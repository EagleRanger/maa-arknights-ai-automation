"""Resume missing daily chains on the selected release, never replay farming."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
import importlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

from daily_dispatch_v1 import ROOT, read, digest, resolve, preflight, selected_scope

WORKFLOW = 'ARK-DAILY-TAIL-V2'
CHAIN_ORDER = ('StartUp', 'Infrast', 'Recruit', 'Mall', 'Award')


def admit(path, at=None):
    path = Path(path).resolve()
    path.relative_to(ROOT/'outputs/continuations')
    p = read(path)
    h = read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json')
    binding = h.get('current_daily_continuation') or {}
    now = at or datetime.now().astimezone()
    if (binding.get('status') != 'READY' or binding.get('workflow') != WORKFLOW
            or (ROOT/binding['handoff']).resolve() != path or binding['handoff_sha256'] != digest(path)
            or p.get('workflow') != WORKFLOW or p.get('scope') != 'missing_daily_tail_no_battles'
            or not datetime.fromisoformat(p['not_before']) <= now < datetime.fromisoformat(p['deadline'])):
        raise ValueError('tail identity/scope/window mismatch')
    for key in ('source_manifest', 'source_report'):
        target = (ROOT/p[key]).resolve()
        target.relative_to(ROOT/'outputs')
        if digest(target) != p[key+'_sha256']:
            raise ValueError('sealed source changed: '+key)
    source, report = read(ROOT/p['source_manifest']), read(ROOT/p['source_report'])
    day = lambda d: (d.replace(tzinfo=None)-timedelta(hours=4)).date()
    if (source['run_id'] != p['source_run_id'] or not source.get('finished_at')
            or source.get('cleanup_verified') is not True
            or day(datetime.fromisoformat(source['started_at'])) != day(now)
            or report.get('fight', {}).get('run_id') != source['run_id']):
        raise ValueError('source run/game-day/cleanup mismatch')
    completed = {k for k in CHAIN_ORDER if report['chain_status'][k].get('ok') is True}
    wanted = {'StartUp'} | (set(CHAIN_ORDER)-completed)
    if set(p['queue']) != wanted:
        raise ValueError('must resume only missing chains plus login')
    for name, sha in p['artifacts'].items():
        if digest(ROOT/name) != sha:
            raise ValueError('tail artifact changed: '+name)
    return p, source, report


def preserved_log(report):
    # Existing engine's partial-chain merger, but with an exact sealed source
    # instead of whichever JSON happens to have today's filename.
    return ''.join(f'TaskChainStart {{"taskchain":"{c}"}}\nTaskChainCompleted {{"taskchain":"{c}"}}\n'
                   for c in CHAIN_ORDER if report['chain_status'][c].get('ok') is True)


def run_scope(app, p, source, report):
    app._DAILY_EXISTING_SANITY_ONLY = True
    app._DAILY_COMPLETION_NOT_BEFORE = datetime.now()
    summary = app._RUN_SUMMARY
    summary['tail_resume'] = dict(source_run_id=source['run_id'], source_manifest=p['source_manifest'],
        source_sha256=p['source_manifest_sha256'], source_report=p['source_report'],
        source_report_sha256=p['source_report_sha256'], queue=p['queue'], new_battles=False)
    if app._ensure_execution_plan('full') is None or app._maa_task_queue_running() is not False:
        return False
    if not app.goto_main_menu():
        return False
    app._capture_stamina_observation('start', navigate=True)
    prior = source['run_summary']
    base = deepcopy(prior['base_333'])
    receipt = deepcopy(p['base_receipt'])
    if not all(receipt.get(k) is True for k in ('config_loaded', 'products_verified',
                                               'operator_rotation_verified', 'task_chain_completed')):
        raise ValueError('prior base evidence unverified; do not pretend it completed')
    if digest(base['config']) != base['config_sha256']:
        raise ValueError('base configuration changed since prior accepted queue')
    base.update(status='applied_verified', execution_receipt=receipt, post_run_config_stable=True,
                preserved_from=source['run_id'])
    summary['base_333'] = base
    for key in ('annihilation', 'mainline', 'security'):
        if key in prior:
            summary[key] = deepcopy(prior[key])
            summary[key]['preserved_from'] = source['run_id']
    summary['final_daily_requested'] = True
    with patch.object(app, '_merge_prior_daily_chain_evidence', lambda current: preserved_log(report)+current):
        done = app.mode_daily(enabled_tasks=set(p['queue'])) is True
    summary['final_daily_completed'] = done
    accepted_log = app._LAST_MAA_RUN_LOG
    if not done:
        return False
    if app._maa_task_queue_running() is not False:
        return False
    # Reuse the existing bounded manufacturing-only repair, no room rotation.
    from daily_base_333_drones_v1 import execute_drone_only
    from daily_base_333_flow_balance_v1 import manufacture_target
    target = manufacture_target(read(base['config']))
    original_wait = app.wait_maa_complete
    def drone_wait(*args, **kwargs):
        # This is the accepted drone-only Infrast plan, not a new six-room
        # rotation. Do not apply the unrelated full-base receipt validator.
        previous_scope = getattr(app, '_base333_active_maa_scope', set())
        app._base333_active_maa_scope = {'DroneOnly'}
        try:
            return original_wait(*args, **kwargs)
        finally:
            app._base333_active_maa_scope = previous_scope
    try:
        with patch.object(app, 'wait_maa_complete', drone_wait):
            usage = execute_drone_only(app, ROOT/p['drone_output'], target=target)
        summary['base_333_drone_usage'] = usage
    finally:
        app._LAST_MAA_RUN_LOG = accepted_log
        summary['daily_requested_chains'] = list(CHAIN_ORDER)
    app.goto_main_menu()
    return done and (usage.get('usage_verified') is True or usage.get('used_up_verified') is True)


def annotate(report, p, source, old_report):
    report['tail_resume_source'] = dict(run_id=source['run_id'], manifest=p['source_manifest'],
        sha256=p['source_manifest_sha256'], report=p['source_report'], report_sha256=p['source_report_sha256'])
    fight = old_report['fight']
    report['same_game_day_verified_totals'] = dict(stage=fight['stage'], total_runs=fight['times_finished'],
        total_cost=fight['total_cost'], prior_runs=fight['times_finished'], current_runs=0,
        total_drops=deepcopy(old_report['drops']), source_run_id=source['run_id'])
    # A failed Mall retry must not erase accepted Infrast/Recruit from today.
    # Preserve the native window separately, and never promote overall success.
    native = deepcopy(report.get('chain_status') or {})
    carried = []
    labels = {'Infrast': '基建换班尚未完成', 'Recruit': '公开招募尚未完成'}
    for chain in labels:
        accepted = old_report['chain_status'].get(chain) or {}
        if accepted.get('ok') is True and not native.get(chain, {}).get('started'):
            report.setdefault('chain_status', {})[chain] = dict(accepted,
                source_run_id=source['run_id'], scope='sealed_prior_same_game_day', executed_in_current_run=False)
            carried.append(chain)
    report['tail_native_chain_status'] = native
    report['preserved_daily_chains'] = carried
    report['domain_issues'] = [s for s in report.get('domain_issues', [])
                              if s not in {labels[c] for c in carried}]
    # Native current-window accounting remains untouched; this is provenance,
    # not a fabricated new Fight receipt or historical final sanity reading.
    return report


@contextmanager
def reporting(p, source, prior_report):
    import daily_final_report_sink_v2 as sink
    import daily_final_report_sink_v1 as presentation
    old_run = sink.run_with_final_sink
    def run(*args, **kwargs):
        old_final = sink.finalize_file
        def finalize(path, **kw):
            # Correct provenance before the sink derives human-readable issues.
            before = annotate(read(path), p, source, prior_report)
            presentation.write_json(Path(path), before)
            result = annotate(old_final(path, **kw), p, source, prior_report)
            presentation.write_json(Path(path), result)
            Path(path).with_suffix('.md').write_text(presentation.markdown(result), encoding='utf-8')
            return result
        with patch.object(sink, 'finalize_file', finalize):
            return old_run(*args, **kwargs)
    with patch.object(sink, 'run_with_final_sink', run):
        yield


def full(p, source, prior_report, selected, checked):
    import run_daily as base
    import daily_workflow_identity_v1 as identity
    old_identity = identity.boundary
    def bind(app, root, _):
        return old_identity(app, root, dict(workflow=WORKFLOW,
            entrypoint='run_daily_tail_v2.py --handoff '+p['packet_path'],
            handoff_id=p['handoff_id'], sha256=digest(__file__)))
    sys.argv = [str(ROOT/'run_daily.py'), '--mode', 'full', '--existing-sanity-only']
    with selected_scope(selected, checked), reporting(p, source, prior_report), \
         patch.object(base, 'run_scope', lambda app: run_scope(app, p, source, prior_report)), \
         patch.object(identity, 'boundary', bind):
        return importlib.import_module(selected['module']).full()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--handoff', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    p, source, report = admit(args.handoff)
    selected = resolve(read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json'))
    checked = preflight(selected)
    if args.check_only:
        print(json.dumps(dict(status='PASS', queue=p['queue'], game_actions=0,
                              preserved_fights=report['fight']['times_finished']))); return 0
    latch = ROOT/p['dispatch_latch']
    latch.resolve().relative_to(ROOT/'outputs/continuations')
    with latch.open('x', encoding='utf-8') as stream:
        json.dump(dict(handoff=p['handoff_id'], at=datetime.now().astimezone().isoformat()), stream)
    return full(p, source, report, selected, checked)


if __name__ == '__main__':
    raise SystemExit(main())
