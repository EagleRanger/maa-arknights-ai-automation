"""Stable daily entry. Reuse the accepted SR farming/final queue implementation.

No date-specific repair, failed-attempt backfill, or Copilot selection belongs here.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parent
ENGINE_FILE = 'arknights_daily_runtime_v12.py'
ENGINE_SHA256 = '37A6D5A695175415ECAD978F0BB42FC8E6615331E4CF0A3F70DE3C2CC7FB902D'
USE_STANDARD_FULL = 'use_standard_full'


def check_entry(at=None):
    """Read-only production routing check; importing this never controls a game."""
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window
    handoff=json.loads((ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json').read_text(encoding='utf-8'))
    contract=json.loads((ROOT/'PROJECT_CONTRACT.json').read_text(encoding='utf-8'))
    if handoff.get('status')!='active' or handoff.get('entrypoint')!='run_daily.py --mode full':
        raise ValueError('Stable daily entry is not the active production route')
    if handoff['workflow_binding']['contract_goal_revision']!=contract['goal_memory']['revision']:
        raise ValueError('Current user contract and daily route disagree')
    now=at or datetime.now().astimezone()
    if handoff.get('valid_until') and now>=datetime.fromisoformat(handoff['valid_until']):
        raise ValueError('Explicit handoff expiry reached')
    gate=resolve_production_recipes(ROOT/'.project-reasoning/COMPONENTS.json',handoff['required_recipes'])
    registry=json.loads((ROOT/'.project-reasoning/COMPONENTS.json').read_text(encoding='utf-8'))
    ids={cid for recipe in gate['resolved'] for cid in recipe['components']}
    for component in registry['components']:
        if component['id'] not in ids:
            continue
        for artifact in component.get('artifacts',[]):
            if artifact['kind']!='file':
                raise ValueError('Stable snapshot expects whole-file artifacts')
            path=(ROOT/artifact['path']).resolve()
            path.relative_to(ROOT)
            if hashlib.sha256(path.read_bytes()).hexdigest().upper()!=artifact['sha256'].upper():
                raise ValueError('Production artifact changed: '+artifact['path'])
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper()!=handoff['production_snapshot_sha256']:
        raise ValueError('Daily entry snapshot changed')
    return {'status':'PASS','entrypoint':handoff['entrypoint'],'checked_at':now.isoformat(),
            'sss_window':reward_window(now),'daily_expired_by_sss':False,'game_actions':0}


def settle_manifest(data, scope_ok, report):
    """Use the current post-cleanup report, never a stale daily JSON file."""
    clean = report.get('all_cleaned') is True
    complete = scope_ok is True and report.get('workflow_completed') is True
    data.update(business_complete=complete, cleanup_verified=clean,
                status='completed' if complete and clean else 'partial_or_blocked',
                report_domain_issues=report.get('domain_issues', []))


def run_stamina_scope(app):
    if app._RUN_SUMMARY.get('page_attention'):
        return False
    if app._ensure_execution_plan('full') is None:
        return False
    from event_availability_v12 import discover_event
    tip = app.save_maa_daily_stage_tip()
    app._RUN_SUMMARY['daily_stage_tip'] = tip
    event = discover_event('月行水上', tip.get('active_side_stories'), app._maa_install_root())
    if not event or event.get('_discovery_status') != 'ready_for_visual_navigation':
        # The SR shortcut is an optimization, not an evergreen event binding.
        # Other dates/events use the original full route (weekly -> live event
        # discovery / mainline -> SSS -> final daily), not a stale SR blocker.
        return USE_STANDARD_FULL
    if not app._run_full_annihilation_step():
        app._block_stamina_flow('当前周剿灭未闭环', source='annihilation')
        return False
    app.ACTIVE_EVENTS.insert(0, event)
    app._RUN_SUMMARY['flow_target'] = {'type': 'event', 'name': event['name']}
    summary = app._RUN_SUMMARY.setdefault('event', {'name': event['name'], 'stages': {}})
    summary['first_clear_replay'] = False
    # Fresh inventory selection already opens the stage and checks its three stars.
    # Do not repeat an unrelated SR-8 audit or first clear before each farm run.
    if not app._configure_new_event_farm_from_live_inventory(event):
        return False
    selection = summary.get('farm_selection') or {}
    if not selection.get('verified') or not selection.get('evidence'):
        return False
    summary['navigation'] = {'status': 'verified', 'stage': selection['stage'],
                            'evidence': selection['evidence'],
                            'detail': '本轮材料关详情、三星和理智消耗已核验'}
    summary['selected_farm_stage'] = event['farm_stage']
    result = app.mode_event(stage_code=event['farm_stage'], times=99)
    summary['farm_result'] = result
    farming = result in (True, 'stamina_exhausted')
    if not farming:
        app._block_stamina_flow('材料代理未闭环', source='daily')
    rewards = False
    if not app._RUN_SUMMARY.get('page_attention'):
        rewards = app.claim_event_task_rewards(event)
    return bool(farming and rewards)


def run_scope(app):
    app._DAILY_COMPLETION_NOT_BEFORE = datetime.now()
    stamina_ok = security_ok = daily_ok = False
    try:
        stamina_ok = run_stamina_scope(app)
        if stamina_ok == USE_STANDARD_FULL:
            return app._FIXED_DAILY_ORIGINAL_FULL()
    except Exception as exc:
        app._RUN_SUMMARY['stamina_error'] = f'{type(exc).__name__}: {exc}'
        app._block_stamina_flow('理智分支异常，安全收尾', source='daily')
        traceback.print_exc()
    # Independent non-stamina work is never skipped merely by a False return.
    try:
        if not app._RUN_SUMMARY.get('page_attention'):
            security_ok = app._run_full_optional_sss_step()
    except Exception as exc:
        app._RUN_SUMMARY['security_error'] = f'{type(exc).__name__}: {exc}'
    app._RUN_SUMMARY['final_daily_requested'] = True
    daily_ok = app._run_full_final_daily_step()
    app._RUN_SUMMARY['final_daily_completed'] = daily_ok is True
    return bool(stamina_ok and security_ok and daily_ok)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['full'], default='full')
    parser.add_argument('--run-id')
    parser.add_argument('--existing-sanity-only', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--check-at', help='ISO timestamp for read-only date regression')
    args = parser.parse_args()
    if args.check_at and not args.check_only:
        parser.error('--check-at is read-only and requires --check-only')
    if args.check_only:
        print(json.dumps(check_entry(datetime.fromisoformat(args.check_at) if args.check_at else None),ensure_ascii=False))
        return 0
    check_entry()
    now = datetime.now().astimezone()
    run_id = args.run_id or 'daily-' + now.strftime('%Y%m%d-%H%M%S-%f')
    if not run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in run_id):
        raise SystemExit('Invalid run identity')
    if hashlib.sha256((ROOT/ENGINE_FILE).read_bytes()).hexdigest().upper() != ENGINE_SHA256:
        raise SystemExit('Daily engine fingerprint changed; do not load an untested engine')
    manifest = ROOT/'outputs/run_manifests'/(run_id + '.json')
    manifest.parent.mkdir(parents=True, exist_ok=True)
    data = {'run_id': run_id, 'workflow': 'ARK-DAILY-STABLE-V1', 'status': 'prepared',
            'created_at': now.isoformat(), 'business_complete': False, 'cleanup_verified': False,
            'existing_sanity_only': args.existing_sanity_only}
    with manifest.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    import arknights_daily_runtime_v12 as app
    app._DAILY_EXISTING_SANITY_ONLY = args.existing_sanity_only
    app._FIXED_DAILY_ORIGINAL_FULL = app.mode_full
    result = {'ok': False}
    original_report = app.generate_daily_report
    def capture_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        result['report'] = report
        return report
    app.generate_daily_report = capture_report
    def scoped(**kwargs):
        try:
            result['ok'] = run_scope(app)
        finally:
            app._RUN_SUMMARY['daily_scope_result'] = {'complete': result['ok'] is True}
        return result['ok']
    app.mode_full = scoped
    sys.argv = [str(ROOT/'run_daily.py'), '--mode', 'full']
    data.update(status='running', started_at=datetime.now().astimezone().isoformat())
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        app.main()
    except BaseException as exc:
        data['error'] = f'{type(exc).__name__}: {exc}'
        traceback.print_exc()
    finally:
        settle_manifest(data, result['ok'], result.get('report') or {})
        data.update(finished_at=datetime.now().astimezone().isoformat(),
                    run_summary=app._RUN_SUMMARY)
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if data.get('status') == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
