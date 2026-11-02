"""Keep bounded fault evidence beside the existing outbox, not rotating frames.

No game input or second delivery queue. Existing acknowledged packets are never
rewritten. Failure to preserve evidence is recorded, not a reason to replay work.
"""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import hashlib
import json
import sys

MAX_IMAGES = 8
MAX_BYTES = 16 * 1024 * 1024


def retained_publisher(original, project_root):
    root = Path(project_root).resolve()

    def publish(output_dir, run_key, stage, reason, observations, battle_result=None):
        identity = json.dumps([run_key, stage, reason], ensure_ascii=False)
        event_id = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]
        folder = Path(output_dir) / 'event_page_attention'
        packet_path = folder / (event_id + '.json')
        if packet_path.exists():
            return str(packet_path)
        rows = deepcopy(observations)
        count = 0
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not row.get('screenshot'):
                continue
            source = row['screenshot']
            row['source_screenshot'] = source
            try:
                path = Path(source)
                path = (root / path).resolve() if not path.is_absolute() else path.resolve()
                if not path.is_relative_to(root) or path.suffix.lower() not in {'.png', '.jpg', '.jpeg'}:
                    row['evidence_retention'] = 'outside_scope_or_not_image'
                    continue
                if not path.is_file():
                    row['evidence_retention'] = 'source_missing'
                    continue
                if count >= MAX_IMAGES or path.stat().st_size > MAX_BYTES:
                    row['evidence_retention'] = 'size_or_count_limit'
                    continue
                # Read at most the allowed size even if a writer grows the file.
                with path.open('rb') as stream:
                    data = stream.read(MAX_BYTES + 1)
                if not data or len(data) > MAX_BYTES:
                    row['evidence_retention'] = 'empty_or_oversized'
                    continue
                digest = hashlib.sha256(data).hexdigest()
                target = folder / event_id / (digest + path.suffix.lower())
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    with target.open('xb') as stream:
                        stream.write(data)
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise OSError('evidence copy hash mismatch')
                row.update(screenshot=str(target.resolve()), evidence_sha256=digest,
                           evidence_retention='retained')
                count += 1
            except (OSError, TypeError, ValueError) as exc:
                row['evidence_retention'] = 'unavailable:' + type(exc).__name__
        return original(output_dir, run_key, stage, reason, rows, battle_result)
    return publish


@contextmanager
def boundary(app):
    import event_page_guard_v1 as guard
    original = guard.publish_page_attention
    wrapped = retained_publisher(original, app.BASE)
    # Several consumers captured the publisher at import time; patch those
    # references too, while imports made later receive the wrapped original.
    with ExitStack() as stack:
        for module in list(sys.modules.values()):
            if module is not None and vars(module).get('publish_page_attention') is original:
                stack.enter_context(patch.object(module, 'publish_page_attention', wrapped))
        yield
