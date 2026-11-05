"""Current-runtime activity farming remainder; no first-clear/weekly/SSS replay."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


def collect_new_tail(app, plan, run_id):
    """Reuse the owned exit collections, not the five-chain daily or drones."""
    from ark_modules.exit_tail import ExitTail
    from ark_modules.operations import BY_NAME
    from ark_modules.orchestration import Context
    from ark_modules.runtime_session import operation_boundary
    from event_attention_identity_v1 import current_run_id
    handle = getattr(app, '_RUN_MUTEX_HANDLE', None)
    revision = plan.get('goal_memory_revision')
    if not (handle and revision and run_id
            and current_run_id(app.BASE, ['--run-id', run_id]) == run_id):
        return dict(status='blocked', reason='current_owner_or_manifest_unverified')
    clock = lambda: datetime.now().astimezone()
    now = clock()
    # Two existing collect() calls, each bounded to at most 600 seconds.
    # This is a collection wait budget, not a daily AI-recovery deadline.
    context = Context(run_id, 'daily-activity-remainder', str(revision), now.isoformat(),
                      (now + timedelta(seconds=1200)).isoformat(), run_id)
    tail = ExitTail(app, Path(app.OUTPUT_DIR)/'continuations'/run_id/'exit_collections', context,
        owns_control=lambda owner: owner == run_id and app._RUN_MUTEX_HANDLE == handle,
        clock=clock)
    with operation_boundary(app, BY_NAME['daily.exit_tail']):
        collections = tail.collect(('Infrast', 'Recruit'), 'collections')
        award = tail.collect(('Award',), 'award')
    return dict(status='succeeded' if collections.status == award.status == 'succeeded' else 'partial',
        collections=asdict(collections), award=asdict(award), full_daily_replayed=False)


def run_scope(app, source, *, run_id=None):
    app._DAILY_EXISTING_SANITY_ONLY = True
    before_run = source.get('run_summary') or {}
    prior_daily_verified = before_run.get('final_daily_completed') is True
    if not prior_daily_verified:
        app._DAILY_COMPLETION_NOT_BEFORE = datetime.now()
    row = app._RUN_SUMMARY['activity_remainder'] = dict(source_run_id=source['run_id'],
        status='checking', steps=['fresh_sanity', 'fresh_activity_inventory', 'activity_farm',
                                 'activity_rewards'],
        skipped=['weekly', 'stage_first_clear', 'sss', 'press_committee'])
    plan = app._ensure_execution_plan('full')
    if plan is None or app._maa_task_queue_running() is not False:
        row.update(status='waiting', reason='current_owner_or_plan_not_ready')
        return False
    if not app._plan_allows('event_farm'):
        row.update(status='blocked', reason='event_farm_not_authorized')
        return False
    if not app.goto_main_menu():
        row.update(status='waiting', reason='home_not_verified')
        return False
    before = app._capture_stamina_observation('start', navigate=False)
    if not before or before.get('verified') is not True or type(before.get('value')) is not int:
        # Reporting uncertainty is not a new authorization gate. The existing
        # stage detail / exhaustion checks still govern each battle, and both
        # launcher and runtime prohibit refill resources for this continuation.
        row['sanity_observation'] = dict(status='unknown', value=None,
            reason='fresh_sanity_not_verified', source=deepcopy(before))
    else:
        row['sanity_observation'] = dict(status='verified', value=before['value'])
    event_name = (before_run.get('event') or {}).get('name')
    farm_ok = rewards_ok = daily_ok = False
    try:
        tip = app.save_maa_daily_stage_tip()
        app._RUN_SUMMARY['daily_stage_tip'] = tip
        event = app.discover_event(event_name, tip.get('active_side_stories'), app.MAA_ROOT)
        if not event or event.get('_discovery_status') != 'ready_for_visual_navigation':
            raise ValueError('source activity unavailable; do not substitute chips or rocks')
        app.ACTIVE_EVENTS.insert(0, event)
        app._RUN_SUMMARY['flow_target'] = dict(type='event', name=event_name)
        summary = app._RUN_SUMMARY.setdefault('event', dict(name=event_name, stages={}))
        summary['first_clear_replay'] = False
        if not app._configure_new_event_farm_from_live_inventory(event):
            raise ValueError('fresh inventory/target detail not yet verified')
        choice = summary.get('farm_selection') or {}
        if choice.get('verified') is not True or not choice.get('evidence'):
            raise ValueError('current stage selection lacks game evidence')
        summary.update(selected_farm_stage=event['farm_stage'],
            navigation=dict(status='verified', stage=event['farm_stage'], evidence=choice['evidence']))
        row['fight_requested'] = True
        result = app.mode_event(stage_code=event['farm_stage'], times=99)
        summary['farm_result'] = result
        farm_ok = result in (True, 'stamina_exhausted')
        if app._plan_allows('event_task_claim') and event.get('task_claim_enabled', True):
            if not app._RUN_SUMMARY.get('page_attention'):
                rewards_ok = app.claim_event_task_rewards(event) is True
                row['activity_rewards_verified'] = rewards_ok
        else:
            row['activity_rewards_status'] = 'not_requested_or_disabled'
            rewards_ok = True
    except Exception as exc:
        row['reason'] = f'{type(exc).__name__}: {exc}'
    finally:
        # Retain the current run's battle evidence before another native chain
        # rotates the log. The existing accounting module still verifies it.
        if row.get('fight_requested'):
            try:
                text = app._get_current_maa_run_log() or ''
                target = Path(app.OUTPUT_DIR) / 'continuations' / (source['run_id'] + '-remainder-fight.log')
                target.parent.mkdir(parents=True, exist_ok=True)
                # Unique output: never replace a previous continuation's log.
                target = target.with_name(target.stem + '-' + datetime.now().strftime('%H%M%S%f') + target.suffix)
                target.write_text(text, encoding='utf-8')
                row['fight_snapshot'] = str(target)
            except Exception as exc:
                row['snapshot_error'] = str(exc)
    # A bound stop/cancellation can propagate as BaseException. Keep the
    # evidence above, but do not start any new collection from that unwind.
    daily_allowed = app._plan_allows('daily')
    app._RUN_SUMMARY['final_daily_requested'] = daily_allowed and not prior_daily_verified
    if prior_daily_verified:
        row['skipped'].append('verified_prior_final_daily')
    if not daily_allowed:
        row['skipped'].append('daily_not_authorized')
        daily_ok = True
    elif prior_daily_verified:
        row['steps'].append('exit_collections_only')
        row['light_tail'] = collect_new_tail(app, plan, run_id)
        daily_ok = row['light_tail']['status'] == 'succeeded'
    else:
        row['steps'].append('post_fight_daily')
        daily_ok = app._run_full_final_daily_step() is True
        app._RUN_SUMMARY['final_daily_completed'] = daily_ok
    row.update(status='completed' if farm_ok and rewards_ok and daily_ok else 'partial',
               farm_completed=farm_ok,
               final_daily_reused=prior_daily_verified,
               final_daily_completed_this_run=bool(daily_allowed and daily_ok and not prior_daily_verified))
    return bool(farm_ok and rewards_ok and daily_ok)


def preserved_issues(source):
    prior = source.get('run_summary') or {}
    pending = [p.get('paper') for p in (prior.get('press_committee') or {}).get('papers', [])
               if p.get('status') not in ('verified_complete', 'locked') and p.get('paper')]
    return ['战时新闻委员会未完成：' + '、'.join(pending)] if pending else []


def annotate(report, source, source_hash):
    prior = source.get('run_summary') or {}
    report['preserved_prior_effects'] = dict(source_run_id=source['run_id'], source_sha256=source_hash,
        scope='same_day_source_effects_not_new_actions',
        annihilation=deepcopy(prior.get('annihilation')),
        final_daily_completed=prior.get('final_daily_completed') is True,
        optional_activity=deepcopy(prior.get('press_committee')),
        source_manifest='outputs/run_manifests/' + source['run_id'] + '.json')
    pending = preserved_issues(source)
    if pending:
        report['domain_issues'] = list(dict.fromkeys([*(report.get('domain_issues') or []), *pending]))
        report.update(workflow_completed=False, overall_status='partial')
    return report


@contextmanager
def reporting(root, source, source_hash):
    import daily_final_report_sink_v2 as sink
    import daily_final_report_sink_v1 as presentation
    import daily_plain_popup_v1 as plain
    import daily_run_accounting_v1 as accounting
    original_reconcile, original_popup, original_attach = sink.reconcile_manifest, plain.summary, accounting.attach
    original_problems = sink.problems
    def problems(report):
        return list(dict.fromkeys([*original_problems(report), *preserved_issues(source)]))
    def attach(report, manifest, *, log_paths=None):
        boundary = (report.get('run_summary') or {}).get('run_evidence_boundary') or {}
        path = Path(boundary['source']) if boundary.get('source') else None
        paths = list(log_paths or ([path.with_name('asst.bak.log'), path] if path else []))
        snapshot = ((report.get('run_summary') or {}).get('activity_remainder') or {}).get('fight_snapshot')
        if snapshot and Path(snapshot).is_file():
            paths.append(Path(snapshot))
        return original_attach(report, manifest, log_paths=paths or None)
    def popup(report):
        annotate(report, source, source_hash)
        return original_popup(report)
    def reconcile(path, report, run_id):
        annotate(report, source, source_hash)
        result = original_reconcile(path, report, run_id)
        result['preserved_prior_effects'] = deepcopy(report['preserved_prior_effects'])
        presentation.write_json(Path(path), result)
        return result
    with patch.object(sink, 'reconcile_manifest', reconcile), patch.object(plain, 'summary', popup), \
         patch.object(accounting, 'attach', attach), patch.object(sink, 'problems', problems):
        yield
