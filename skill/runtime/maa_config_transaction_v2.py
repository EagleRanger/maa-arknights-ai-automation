"""Undo only this task's fields; preserve MAA's concurrent migrations."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import json

MISSING = object()


def restore(original, temporary, current):
    if original == temporary:
        return deepcopy(current)
    if isinstance(original, dict) and isinstance(temporary, dict) and isinstance(current, dict):
        result = deepcopy(current)
        for key in original.keys() | temporary.keys():
            a, b, c = original.get(key, MISSING), temporary.get(key, MISSING), current.get(key, MISSING)
            if a == b:
                continue
            if a is MISSING:
                if c == b:
                    result.pop(key, None)
            elif b is MISSING:
                if c is MISSING:
                    result[key] = deepcopy(a)
            elif c is not MISSING:
                result[key] = restore(a, b, c)
        return result
    if (isinstance(original, list) and isinstance(temporary, list) and isinstance(current, list)
            and len(original) == len(temporary) == len(current)
            and all(isinstance(x, dict) for x in original + temporary + current)
            and [x.get('TaskType') for x in original] == [x.get('TaskType') for x in temporary]
            == [x.get('TaskType') for x in current]):
        return [restore(a, b, c) for a, b, c in zip(original, temporary, current)]
    return deepcopy(original if current == temporary else current)


@contextmanager
def boundary(app):
    @contextmanager
    def temporary(mutator, description):
        path = Path(app.MAA_CONFIG) / 'gui.new.json'
        original = json.loads(path.read_text('utf-8-sig'))
        changed = deepcopy(original)
        mutator(changed)
        app._atomic_write_json(str(path), changed)
        app.log('→ MAA临时配置已应用: ' + description)
        try:
            yield str(path)
        finally:
            current = json.loads(path.read_text('utf-8-sig'))
            app._atomic_write_json(str(path), restore(original, changed, current))
            app.log('→ MAA临时任务字段已恢复；保留本轮更新迁移和其它未改字段')
    with patch.object(app, 'temporary_maa_config', temporary):
        yield
