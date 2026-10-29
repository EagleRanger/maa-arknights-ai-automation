"""Bounded same-file OCR reuse and operation timings; never reduce fresh checks."""
from collections import OrderedDict
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from unittest.mock import patch


@contextmanager
def boundary(app):
    cache = OrderedDict()
    metrics = {'version': 1, 'ocr_cache_hits': 0, 'operations': {}}
    def wrap(name, function):
        def call(*args, **kwargs):
            # Path + nanosecond timestamp + size + inode binds immutable captures.
            key = None
            if name in ('ocr', 'ocr_text') and len(args) == 1 and not kwargs:
                try:
                    p = Path(args[0]); s = p.stat()
                    key = (name, str(p.resolve()), s.st_mtime_ns, s.st_ctime_ns, s.st_size, s.st_ino)
                except (OSError, TypeError):
                    pass
            if key is not None and key in cache:
                metrics['ocr_cache_hits'] += 1
                cache.move_to_end(key)
                return deepcopy(cache[key])
            started = perf_counter()
            try:
                result = function(*args, **kwargs)
                if key is not None:
                    cache[key] = deepcopy(result)
                    while len(cache) > 16:
                        cache.popitem(last=False)
                return result
            finally:
                elapsed = perf_counter() - started
                row = metrics['operations'].setdefault(name, {'calls': 0, 'seconds': 0.0, 'max_seconds': 0.0})
                row['calls'] += 1; row['seconds'] += elapsed
                row['max_seconds'] = max(row['max_seconds'], elapsed)
                app._RUN_SUMMARY['execution_timing'] = metrics
        return call
    with ExitStack() as stack:
        for name in ('shot', 'ocr', 'ocr_text', 'goto_main_menu', 'wait_maa_complete'):
            function = getattr(app, name, None)
            if callable(function):
                stack.enter_context(patch.object(app, name, wrap(name, function)))
        yield metrics
