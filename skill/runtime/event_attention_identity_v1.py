"""Bind new navigation feedback to the explicit current manifest, not a guess."""
from contextlib import contextmanager, ExitStack
import hashlib
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch


def current_run_id(root, argv=None):
    args = list(sys.argv if argv is None else argv)
    try:
        value = args[args.index('--run-id') + 1]
        if not re.fullmatch(r'[A-Za-z0-9_-]+', value):
            return None
        data = json.loads((Path(root) / 'outputs/run_manifests' / (value + '.json')).read_text('utf-8'))
        return value if data.get('run_id') == value else None
    except (ValueError, IndexError, OSError, TypeError):
        return None


def bind_publisher(original, app, argv=None):
    def publish(output_dir, run_key, stage, reason, observations, battle_result=None):
        event_id = hashlib.sha256(json.dumps([run_key, stage, reason], ensure_ascii=False).encode('utf-8')).hexdigest()[:20]
        path = Path(output_dir) / 'event_page_attention' / (event_id + '.json')
        existed = path.exists()
        result = original(output_dir, run_key, stage, reason, observations, battle_result)
        # Old evidence and delivery acknowledgements are never backfilled.
        if existed:
            return result
        run_id = current_run_id(app.BASE, argv() if argv else None)
        if not run_id or (str(run_key).startswith('daily-') and run_key != run_id):
            app.log('[异常回传] 缺少一致的当前运行身份；保留待处理证据，不推测运行编号', 'WARN')
            return result
        try:
            data = json.loads(path.read_text('utf-8'))
            if data.get('run_id') or data.get('delivery_status') != 'pending':
                return result
            if data.get('event_id') != event_id or data.get('run_key') != run_key:
                return result
            data.update(run_id=run_id, identity_source='explicit_run_id_and_matching_manifest')
            temp = path.with_suffix('.identity.tmp')
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(path)
        except (OSError, ValueError, TypeError) as exc:
            app.log('[异常回传] 运行身份写入失败: ' + type(exc).__name__, 'WARN')
        return result
    return publish


@contextmanager
def boundary(app):
    import event_page_guard_v1 as guard
    import run_daily as base
    original = guard.publish_page_attention
    old_main = base.main
    captured = {}
    def main(*args, **kwargs):
        # run_daily.main intentionally strips --run-id before app.main. Keep
        # that explicit identity at its real entry, before the argv reset.
        captured['argv'] = list(sys.argv)
        return old_main(*args, **kwargs)
    wrapped = bind_publisher(original, app, lambda: captured.get('argv', []))
    with ExitStack() as stack:
        stack.enter_context(patch.object(base, 'main', main))
        for module in list(sys.modules.values()):
            if module is not None and vars(module).get('publish_page_attention') is original:
                stack.enter_context(patch.object(module, 'publish_page_attention', wrapped))
        yield
