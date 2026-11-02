"""Rebuild the pinned YW metadata from receiver-obtained source JSON, offline.

No download, game start, author progress, job import or resource installation.
Acquire the three JSON files from DATA_BASE yourself; source license/terms remain
the upstream's. The public Skill intentionally does not redistribute this data.
"""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
DATA_COMMIT = '17759cc8cdf37388414145d16262a3a06f3ab25e'
DATA_BASE = f'https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/{DATA_COMMIT}/zh_CN/gamedata/excel/'
EXPECTED_SHA = 'F0BE6E6663C6C75B08549FAEC9FEFD37A08475FF2B9AFC68EEFF0B838516E264'

def encode_catalog(activity_data, stage_data, zone_data):
    activities = [v for v in activity_data['basicInfo'].values() if v.get('name') == '昨日海']
    if len(activities) != 1:
        raise ValueError('unique YW activity missing')
    activity = activities[0]
    urls = dict(levels='https://raw.githubusercontent.com/yuanyan3060/Arknights-Bot-Resource/9bf239661e37766fba585806fb9fa67e79bb679e/levels.json',
                activity=DATA_BASE+'activity_table.json',stages=DATA_BASE+'stage_table.json',zones=DATA_BASE+'zone_table.json')
    for number,job in enumerate((105692,105703,105704,105707,105708,105721,105725,105726),1):
        urls[f'YW-{number}'] = f'https://prts.maa.plus/copilot/get/{job}'
    catalog = dict(name='昨日海',activity=activity,
        stages=[v for v in stage_data['stages'].values() if str(v.get('code') or '').startswith('YW-')],
        zones={k:v for k,v in zone_data['zones'].items() if k.startswith(activity['id'])},
        source_urls=urls,game_actions=0)
    raw = (json.dumps(catalog,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    if hashlib.sha256(raw).hexdigest().upper() != EXPECTED_SHA:
        raise ValueError('pinned YW catalog identity mismatch; no output or weakened hash')
    return raw

def prepare(source_dir, *, root=ROOT):
    source_dir = Path(source_dir)
    data = [json.loads((source_dir/name).read_text('utf-8-sig'))
            for name in ('activity_table.json','stage_table.json','zone_table.json')]
    raw = encode_catalog(*data)
    destination = Path(root)/'recipient_resources/yw/catalog.json'
    if destination.exists() and destination.read_bytes() != raw:
        raise ValueError('preserve conflicting local catalog; review it before replacement')
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(raw)
    if hashlib.sha256(destination.read_bytes()).hexdigest().upper() != EXPECTED_SHA:
        raise ValueError('YW catalog readback failed')
    return dict(status='pinned_catalog_ready_not_live_event_admission',sha256=EXPECTED_SHA)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',required=True,type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_dir),ensure_ascii=False))

if __name__ == '__main__':
    main()
