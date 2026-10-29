"""One executable daily selection; historical scopes are not release pointers.

The ordinary scheduler and repair continuation use this same resolver. Selecting
a tested release is not a new authorization, nor evidence of live completion.
The existing engine still owns exclusivity, resource limits and final cleanup.
"""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import argparse
import hashlib
import importlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def resolve(handoff, root=ROOT):
    """Read only the explicit daily binding, never a special task or prose."""
    if handoff.get('status') != 'active':
        raise ValueError('每日入口已暂停，不能启动')
    selected = handoff.get('daily_runtime')
    if not isinstance(selected, dict) or selected.get('status') != 'active':
        raise ValueError('缺少当前每日发布入口；不静默回退历史版本')
    entry = selected.get('entrypoint', '')
    match = re.fullmatch(r'(run_daily_v\d+\.py) --mode full', entry)
    if not match:
        raise ValueError('每日发布入口格式不符')
    if digest(Path(root) / match[1]) != selected.get('sha256'):
        raise ValueError('每日发布入口内容已变化')
    if not selected.get('component_id'):
        raise ValueError('每日发布缺少组件身份')
    for rel, sha in selected.get('launcher_artifacts', {}).items():
        path = (Path(root) / rel).resolve()
        path.relative_to(Path(root).resolve())
        if digest(path) != sha:
            raise ValueError('每日启动器内容已变化: ' + rel)
    return dict(selected, module=match[1][:-3])


def preflight(selected, at=None):
    # The old accepted recipe is a dependency baseline, not a dispatch fallback.
    from run_daily_v112 import check_entry as baseline_check
    from daily_runtime_target_v1 import inventory
    import arknights_daily_runtime_v12 as app
    result = baseline_check(at)
    registry = read(ROOT / '.project-reasoning/COMPONENTS.json')
    by_id = {row['id']: row for row in registry['components']}
    if by_id[selected['component_id']].get('entry') != selected['module'] + '.py':
        raise ValueError('每日入口与组件身份不一致')
    pending, seen = [selected['component_id']], set()
    while pending:
        cid = pending.pop()
        if cid in seen:
            continue
        row = by_id[cid]
        if row['status'] not in {'verified', 'validation_only'}:
            raise ValueError('每日组件不可用: ' + cid)
        for artifact in row.get('artifacts', []):
            if artifact.get('kind') == 'file' and digest(ROOT / artifact['path']) != artifact['sha256'].upper():
                raise ValueError('每日组件内容已变化: ' + artifact['path'])
        seen.add(cid)
        pending.extend(row.get('dependencies', []))
    return dict(result, selected_entrypoint=selected['entrypoint'],
                selected_component=selected['component_id'],
                game_runtime_target=inventory(app.MUMU_CLI), game_actions=0)


@contextmanager
def selected_scope(selected, checked):
    """Adapt the legacy candidate's date gate to the one current daily release.

Only the old *normal-daily candidate* selector is replaced. Explicit special
scope, exclusive controller, resources, run records and game gates are intact.
The baseline/changed dependency checks have already run once in this process.
"""
    import run_daily_v116 as legacy
    def require_current(handoff, at=None):
        current = resolve(handoff)
        if (current['entrypoint'], current['sha256'], current['component_id']) != (
                selected['entrypoint'], selected['sha256'], selected['component_id']):
            raise ValueError('每日发布入口在启动前改变')
        return current
    with patch.object(legacy, 'require_normal_daily', require_current), \
         patch.object(legacy, 'check_entry', lambda at=None, packet=None: checked):
        yield


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--resolve-only', action='store_true')
    args = parser.parse_args(argv)
    selected = resolve(read(ROOT / '.project-reasoning/AUTOMATION_HANDOFF.json'))
    if args.resolve_only:
        print(json.dumps(selected, ensure_ascii=False))
        return 0
    checked = preflight(selected)
    print(json.dumps(checked, ensure_ascii=False), flush=True)
    if args.check_only:
        return 0
    entry = importlib.import_module(selected['module'])
    sys.argv = [str(ROOT / 'run_daily.py'), '--mode', 'full']
    with selected_scope(selected, checked):
        return entry.full()


if __name__ == '__main__':
    raise SystemExit(main())
