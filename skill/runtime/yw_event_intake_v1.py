"""Candidate-only YW intake, independent of the lagging MAA calendar.

Game data and the Tile-Pos upstream identify YW as act52side. Selected PRTS
uploads label it act55side. Keep original uploads; correct only their lookup
identity in a separate trial copy. This is not a game-clear certificate.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'outputs/yw_20261009/candidates'
OUT = ROOT / 'outputs/yw_20261009/admitted_candidates'
ALIASES = ('昨日海', '咋日海', '唯日海')

def canonical_name(value):
    token = re.sub(r'[<>《》〈〉「」『』\s]', '', str(value or ''))
    return '昨日海' if token in ALIASES else None

def adapt_job(job, stage, tile):
    code = stage['code']
    if not re.fullmatch(r'YW-[1-8]', code):
        raise ValueError('Only the inspected normal YW family is in scope')
    suffix = f"{int(code.split('-')[-1]):02d}"
    expected = 'act52side_' + suffix
    if (stage['stageId'] != expected or tile['stageId'] != expected or tile['code'] != code
            or tile['name'] != stage['name'] or tile['levelId'].lower() != stage['levelId'].lower()):
        raise ValueError('Game data and tile identity disagree')
    if job.get('stage_name') not in (expected, 'act55side_' + suffix):
        raise ValueError('Unrecognized source identity')
    titles = re.findall(r'(?<![A-Z0-9-])YW-0?([1-8])(?![0-9])',job.get('doc',{}).get('title','').upper())
    if titles != [str(int(suffix))]:
        raise ValueError('Source title does not name this exact operation')
    actions = job.get('actions')
    if not actions or not any(a.get('type')=='Deploy' for a in actions):
        raise ValueError('No executable deployment sequence')
    for a in actions:
        p=a.get('location')
        if p is not None and (len(p)!=2 or any(type(n)is not int for n in p)
                or not (0<=p[0]<tile['width'] and 0<=p[1]<tile['height'])):
            raise ValueError('Source action outside verified map')
    result=deepcopy(job)
    result['stage_name']=expected
    # All clicks, placement, timing, skills and roster remain source-exact.
    assert {k:v for k,v in result.items() if k!='stage_name'} == {k:v for k,v in job.items() if k!='stage_name'}
    return result

def event_config(catalog, now=None):
    a=catalog['activity']
    now=now or datetime.now(timezone.utc)
    if a['name']!='昨日海' or a['id']!='act52side' or not a['startTime']<=now.timestamp()<a['endTime']:
        raise ValueError('YW activity not currently open')
    rows=catalog['stages']
    normal=[dict(display=s['code'], internal=s['stageId'], modes=['normal'],ap_cost=s['apCost'])
            for s in rows if re.fullmatch(r'YW-[1-8]',s['code'])]
    if len(normal)!=8:
        raise ValueError('Normal stage coverage incomplete')
    section=catalog['zones']['act52side_zone1']['zoneNameSecond']
    return dict(name='昨日海', kind='new', stage_prefix='YW',
                start=datetime.fromtimestamp(a['startTime']).isoformat(),
                end=datetime.fromtimestamp(a['endTime']).isoformat(),
                entry_keywords=list(ALIASES), combat_keywords=[section],section_keywords={'normal':[section]},
                stages=normal, first_clear_modes=['normal'], farm_stage=None,
                tutorial_stages=[dict(display=s['code'],internal=s['stageId'],modes=['normal'])
                                 for s in rows if '-TR-' in s['code']],
                story_stages=[s['code'] for s in rows if '-ST-' in s['code']],
                _discovery_status='candidate_requires_live_navigation',
                _source='pinned game data + Tile-Pos upstream + actual terminal screenshot')

def choose_farm(catalog, tip, *, now, not_before):
    """A proposal, not battle permission; never need the stale MAA calendar."""
    event_config(catalog, now)
    depot=(tip or {}).get('depot') or {}
    if depot.get('fresh') is not True:
        return None
    try:
        sync=datetime.fromisoformat(depot['sync_time'])
        if sync.tzinfo is None or not not_before<=sync<=now:
            return None
    except (TypeError,ValueError,KeyError):
        return None
    options=[]
    for s in catalog['stages']:
        if s['code'] not in ('YW-6','YW-7','YW-8'):
            continue
        drops=[d['id'] for d in s['stageDropInfo']['displayDetailRewards']
               if d['type']=='MATERIAL' and d['dropType']=='NORMAL' and d['occPercent']=='USUAL']
        if len(drops)!=1:
            return None
        count=(depot.get('counts') or {}).get(drops[0])
        # Unknown or omitted material must not be interpreted as zero.
        if type(count) is not int or count<0:
            return None
        options.append(dict(stage=s['code'],drop_id=drops[0],inventory=count,cost=s['apCost']))
    if len(options)!=3:
        return None
    return dict(min(options,key=lambda x:(x['inventory'],x['stage'])),
                inventory_sync_time=sync.isoformat(),requires_live_three_star_and_cost=True)

def build():
    from vector_special_resources_v1 import digest
    source=json.loads((SOURCE/'candidate_manifest.json').read_text(encoding='utf-8'))
    catalog=json.loads((SOURCE/'catalog.json').read_text(encoding='utf-8'))
    config=event_config(catalog)
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    for row in source['stages']:
        job_path=ROOT/row['job_path']; tile_path=ROOT/row['tile_path']
        if digest(job_path)!=row['job_sha256'] or digest(tile_path)!=row['tile_sha256']:
            raise ValueError('Source fingerprint changed')
        job=json.loads(job_path.read_text(encoding='utf-8'))
        tile=json.loads(tile_path.read_text(encoding='utf-8'))
        stage=next(s for s in catalog['stages'] if s['code']==row['code'])
        corrected=adapt_job(job,stage,tile)
        target=OUT/job_path.name
        target.write_text(json.dumps(corrected,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        rows.append(dict(row,job_path=str(target.relative_to(ROOT)),job_sha256=digest(target),
                         source_job_path=row['job_path'],source_job_sha256=row['job_sha256'],
                         identity_matches=True,adaptation='stage_name_only_act55_to_game_data_act52',
                         game_clear_verified=False))
    manifest=dict(status='offline_candidates_verified',game_actions=0,stages=rows,
                  source_manifest=str((SOURCE/'candidate_manifest.json').relative_to(ROOT)),
                  event=config,production_ready=False, requires='live detail identity and map geometry before trial')
    path=OUT/'candidate_manifest.json'
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return path

if __name__=='__main__':
    print(build())
