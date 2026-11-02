"""V1 normal retrospective plus exact bootstrap-only startup-failure evidence."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import json
import re
import daily_post_run_review_v1 as previous

COMPONENT = 'ARK-DAILY-LOGIN-SUPPLY-POSTFLIGHT-V1-CANDIDATE'


def startup_review(bootstrap_path, *, root):
    root = Path(root).resolve()
    bootstrap_path = Path(bootstrap_path).resolve()
    bootstrap_path.relative_to(root / 'outputs/bootstrap_receipts')
    boot, boot_sha = previous.load(bootstrap_path)
    run = boot.get('run_id')
    if (not isinstance(run, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', run)
            or bootstrap_path.stem != run or not boot.get('finished_at')):
        raise ValueError('bootstrap identity not settled')
    path = Path(boot['manifest_path']).resolve()
    if path != root / 'outputs/run_manifests' / (run + '.json'):
        raise ValueError('bootstrap manifest target mismatch')
    manifest, sha = previous.load(path)
    summary = manifest.get('run_summary') or {}
    login = summary.get('login_visual') or {}
    if (manifest.get('run_id') != run or not manifest.get('finished_at')
            or manifest.get('business_complete') is True or login.get('home_verified') is not False
            or not summary.get('run_evidence_boundary')):
        raise ValueError('only precise failed-startup receipts use fallback review')
    result = dict(schema_version=1, component=COMPONENT, run_id=run,
        status='needs_project_review', needs_project_review=True,
        source_manifest=str(path), source_report=None,
        source_sha256={str(path): sha, str(bootstrap_path): boot_sha},
        source_finished_at=manifest['finished_at'],
        findings=[dict(kind='startup_home_unverified', detail='登录未到首页，未进入日常业务',
                       evidence=login)],
        observations=dict(cleanup_verified=manifest.get('cleanup_verified'),
                          sanity=None, battle_effects_not_inferred=True),
        game_actions=0, source_reports_changed=False, automatic_code_changes=False,
        automatic_lesson_promotion=False,
        next_action='项目修复登录首因并验证，再仅接续未完成日常；不读取旧日报补成完成')
    destination = root / 'outputs/module_reviews' / (run + '.post-v2.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        cached, _ = previous.load(destination)
        if cached.get('source_sha256') != result['source_sha256']:
            raise ValueError('startup evidence changed; preserve previous review')
        result = cached
    else:
        from daily_final_report_sink_v1 import write_json
        write_json(destination, result)
    return previous.publish(result, destination, root)


@contextmanager
def boundary(root):
    import daily_final_report_sink_v2 as sink
    import run_daily_v78 as bootstrap
    old_final, old_reconcile, old_save = sink.finalize_file, sink.reconcile_manifest, bootstrap._save
    captured = {}
    def finalize(path, **kw):
        result = old_final(path, **kw)
        captured['report_path'] = Path(path)
        return result
    def reconcile(path, report, run_id):
        result = old_reconcile(path, report, run_id)
        captured['manifest_path'] = Path(path)
        return result
    def save(path, data):
        result = old_save(path, data)
        if data.get('finished_at') and data.get('run_id'):
            captured['bootstrap_path'] = Path(path)
        return result
    try:
        with patch.object(sink, 'finalize_file', finalize), \
             patch.object(sink, 'reconcile_manifest', reconcile), patch.object(bootstrap, '_save', save):
            yield
    finally:
        try:
            if 'report_path' in captured and 'manifest_path' in captured:
                result = previous.evaluate(captured['report_path'], captured['manifest_path'], root=root)
            elif 'bootstrap_path' in captured:
                result = startup_review(captured['bootstrap_path'], root=root)
            else:
                raise ValueError('未捕获同run最终sink或bootstrap封口证据')
            previous.emit(result, None, None)
        except Exception as exc:
            try:
                print('ARK_DAILY_REVIEW_UNAVAILABLE ' + json.dumps(dict(
                    reason=str(exc)[:600], game_actions=0, source={k:str(v) for k,v in captured.items()}),
                    ensure_ascii=False), flush=True)
            except Exception:
                pass
