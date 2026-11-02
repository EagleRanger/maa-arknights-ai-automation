"""Read-only network/saved-image preparation; never connect to the game."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'outputs/annihilation_rotation_20261026'


def save(path, value):
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')
    if path.exists() and path.read_bytes() != payload:
        raise ValueError('Do not overwrite prior research: ' + str(path))
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest().upper()


def main():
    import arknights_daily_runtime_v12 as app
    from local_ocr_v6_small_v1 import reader
    OUT.mkdir(parents=True, exist_ok=True)
    base = 'https://raw.githubusercontent.com/MaaAssistantArknights/MaaResource/main/resource/Arknights-Tile-Pos/'
    overview = app._fetch_prts_json(base + 'overview.json', timeout=15)
    matches = [(key, row) for key, row in overview.items()
               if row.get('stageId') == 'camp_r_34' and row.get('name') == '灰石剧场']
    if len(matches) != 1:
        raise ValueError('Official exact map not unique')
    key, row = matches[0]
    tile = app._fetch_prts_json(base + row['filename'], timeout=15)
    tile_hash = save(OUT / row['filename'], tile)
    response = app._fetch_prts_json('https://prts.maa.plus/copilot/get/108007', timeout=15)
    job = json.loads(response['data']['content'])
    if job['stage_name'] != row['stageId'] or not job.get('actions'):
        raise ValueError('Exact copilot payload missing')
    job_hash = save(OUT / 'camp_r_34_v108007.json', job)
    image = ROOT / 'runtime_screenshots/annihilation_rotation_detail_0_0_1792987827684815700.png'
    with reader() as ocr:
        rows, seconds = ocr(image)
    observations = [(text, int(sum(p[0] for p in box)/4), int(sum(p[1] for p in box)/4))
                    for box, text, score in rows]
    save(OUT / 'detail_ocr.json', dict(image=str(image), rows=observations, historical_replay=True))
    metadata = dict(stage_id=row['stageId'], name=row['name'], overview_key=key, overview_row=row,
        tile_path=str((OUT/row['filename']).relative_to(ROOT)), tile_sha256=tile_hash,
        source=base+row['filename'], overview_source=base+'overview.json',
        job_path=str((OUT/'camp_r_34_v108007.json').relative_to(ROOT)), job_sha256=job_hash,
        job_source='https://prts.maa.plus/copilot/get/108007', job_id=108007,
        original_author='自在道爷', copied_by='星之海.',
        image=str(image.relative_to(ROOT)), actual_game_actions=0)
    save(OUT/'bundle.json', metadata)
    print(json.dumps(dict(bundle=str(OUT/'bundle.json'), map=row, tile_keys=list(tile),
        job_doc=job['doc'], opers=job['opers'], actions=job['actions'],
        rows=observations, game_actions=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
