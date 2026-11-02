"""Keep the existing post-run event compatible with native run-bound delivery."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import json


@contextmanager
def boundary():
    import daily_post_run_review_v1 as review
    from daily_final_report_sink_v1 import write_json
    old = review.publish

    def publish(result, destination, root):
        published = old(result, destination, root)
        path = published.get('attention_path')
        if path:
            packet = json.loads(Path(path).read_text('utf-8-sig'))
            run = result['run_id']
            if any(packet.get(k, run) != run for k in ('run_id', 'run_key', 'source_run_id')):
                raise ValueError('Feedback run identity conflict')
            packet['run_id'] = run
            write_json(Path(path), packet)
        return published

    with patch.object(review, 'publish', publish):
        yield
