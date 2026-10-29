"""Read-only navigation watchdog and deduplicated project-lane outbox.

No game input, scheduling, or direct writes to Codex task storage.
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path


def is_tarot_reward(text):
    text = ''.join(str(text or '').split())
    return ('获得了塔罗牌' in text and '塔罗牌盒' in text
            and '已获取' in text)


def tarot_close_point(image_path):
    """Locate the bright close mark inside the observed SR overlay's close ROI."""
    from PIL import Image
    with Image.open(image_path) as image:
        image = image.convert('RGB')
        w, h = image.size
        left, top = int(w * .78), int(h * .27)
        roi = image.crop((left, top, int(w * .85), int(h * .35)))
        points = [(x, y) for y in range(roi.height) for x in range(roi.width)
                  if min(roi.getpixel((x, y))) >= 235]
    if len(points) < 20:
        return None
    xs, ys = zip(*points)
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    if not (.008 * w < bw < .065 * w and .012 * h < bh < .075 * h):
        return None
    return left + (min(xs) + max(xs)) // 2, top + (min(ys) + max(ys)) // 2


def publish_page_attention(output_dir, run_key, stage, reason, observations,
                           battle_result=None):
    identity = json.dumps([run_key, stage, reason], ensure_ascii=False)
    event_id = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]
    folder = Path(output_dir) / 'event_page_attention'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (event_id + '.json')
    if path.exists():
        return str(path)  # Preserve any delivery acknowledgement.
    packet = dict(schema_version=1, project_loop_id='auto-arknights-project-loop',
                  source='event_page_guard_v1', destination='project_lane',
                  event_id=event_id, run_key=run_key, stage=stage,
                  reason=reason, status='navigation_unverified',
                  created_at=datetime.now().astimezone().isoformat(),
                  delivery_status='pending', needs_attention=True,
                  battle_result=battle_result, retry_battle_allowed=False,
                  observations=observations)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)
    return str(path)
