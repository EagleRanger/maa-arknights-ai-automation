"""Permanent mainline completion, invalidated by actual new-content evidence."""
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'config/mainline_completion_cache.json'


def read_cache(path=CACHE):
    try:
        result = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if (result.get('status') != 'all_current_mainline_verified_complete'
            or result.get('confirmed_by_user') is not True or not result.get('evidence')):
        return None
    return result


def new_content_confirmed(cache, notification=None):
    notice = notification or cache.get('new_content_notification') or {}
    return (notice.get('confirmed') is True and notice.get('kind') == 'mainline_new_content'
            and bool(notice.get('evidence')))


def install(runtime, cache_path=CACHE):
    original = runtime.mode_mainline

    @wraps(original)
    def use_permanent_completion(*args, **kwargs):
        cache = read_cache(cache_path)
        target = kwargs.get('target_stage') or (args[1] if len(args) > 1 else None)
        notice = getattr(runtime, '_mainline_new_content_notification', None)
        if target or cache is None or new_content_confirmed(cache, notice):
            return original(*args, **kwargs)
        runtime._RUN_SUMMARY['mainline'] = dict(
            status='completed', progressed=False, newly_cleared=[], newly_imperfect=[],
            newly_shelved=[], detail='已核验的主线长期复用；没有新章节提示，不重新进入地图',
            scan_performed=False, completion_reused_from=cache['evidence'],
            completion_basis='permanent_mainline_completion_not_daily_cache',
            verified_chapters=deepcopy(cache.get('verified_chapters', [])))
        runtime.log('[主线完成缓存] 既有主线已闭合，无更新提示；跳过整章导航和扫描')
        return True

    runtime.mode_mainline = use_permanent_completion
    return original


@contextmanager
def engine_boundary(runtime, cache_path=CACHE):
    old_main = runtime.main
    installed_original = []
    @wraps(old_main)
    def main(*args, **kwargs):
        # Install after legacy adapters, including the same-day-only wrapper.
        installed_original.append(install(runtime, cache_path))
        return old_main(*args, **kwargs)
    runtime.main = main
    try:
        yield
    finally:
        runtime.main = old_main
        if installed_original:
            runtime.mode_mainline = installed_original[0]
