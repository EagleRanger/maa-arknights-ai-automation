"""2026 CN OS rerun: MAA's SSReopen is a calendar category, not a stage prefix.

Window/chapters/task panel: https://ak.hypergryph.com/news/2808
Objectives: act46sre missionData in zh_CN/gamedata/excel/activity_table.json.
Map ids and AP: act46side records in stage_table.json. Local MAA tiles and the
current calendar are revalidated; nothing in this profile proves account progress.
"""
from contextlib import contextmanager
from datetime import datetime,timezone
import json
import re
import unicodedata
from pathlib import Path
from unittest.mock import patch
from event_availability_v12 import exact_name

NAME='雪山降临1101'
START=datetime.fromisoformat('2026-11-22T04:00:00+08:00')
END=datetime.fromisoformat('2026-12-02T03:59:59+08:00')
SECTIONS={'normal':['圣巡之旅'],'ex':['变革之路'],'s':['喀兰之心']}


def calendar_identity(name,stories,at):
    """Read only this event's calendar row. A neighbouring rerun badge is not its identity."""
    norm=lambda s:exact_name(unicodedata.normalize('NFKC',str(s or '')))
    matches=[]
    for row in stories or []:
        if norm(row.get('name'))!=norm(name):continue
        try:
            if datetime.fromisoformat(row['start_utc'])<=at<datetime.fromisoformat(row['expire_utc']):matches.append(row)
        except (ValueError,TypeError,KeyError):continue
    return matches[0] if len(matches)==1 else None


def fallback_route(name,row,root,at,previous):
    """Resolve a map prefix from the named row, never from a neighbouring event or a drop name."""
    from event_availability_v12 import discover_event as map_catalog
    codes=[str(s.get('stage','')) for s in row.get('stages',[]) if isinstance(s,dict)]
    markers={s[len('SSReopen-'):] for s in codes if s.startswith('SSReopen-')}
    prefixes={m[1] for s in codes if (m:=re.fullmatch(r'([A-Z]{1,6})-[1-9]\d*',s))}
    if not prefixes and len(markers)==1 and re.fullmatch(r'[A-Z]{1,6}',next(iter(markers))):
        prefixes=set(markers)
    rerun=row.get('key')=='SSReopen' or bool(markers)
    if rerun and previous and previous.get('kind')=='rerun' and previous.get('replay_stages'):
        return previous
    if previous and previous.get('_discovery_status')=='ready_for_visual_navigation' and not rerun:return previous
    if len(prefixes)!=1 or (markers and markers!=prefixes):return previous if not rerun else dict(
        name=name,kind='rerun',stages=[],_discovery_status='metadata_unverified',_discovery_reason='复刻日历关卡前缀不唯一')
    prefix=next(iter(prefixes))
    if not rerun and row.get('key') not in ('SideStory','SS','SSOpen',prefix):return previous
    candidate=map_catalog(row['name'],[dict(row,key=prefix)],root,now=at)
    if not candidate or candidate.get('_discovery_status')!='ready_for_visual_navigation':
        return previous if not rerun else dict(name=row['name'],kind='rerun',stage_prefix=prefix,stages=[],
            _discovery_status='metadata_unverified',_discovery_reason='已定位复刻日历；活动入口、篇章或本地地图仍待确认')
    if not rerun:return candidate
    # A shortcut such as “代理1~9关” supplies map evidence, not the reset mission list.
    return dict(candidate,kind='rerun',stages=[],first_clear_modes=[],replay_stages=[],
        _discovery_status='metadata_unverified',_discovery_reason=f'已识别复刻地图{prefix}及篇章，缺本期重置任务表；不套首通',
        intake=dict(prefix=prefix,chapter=candidate.get('combat_keywords'),calendar_key=row.get('key')))


def profile(name,stories,root,now=None):
    at=now or datetime.now(timezone.utc)
    if exact_name(name)!=NAME or at.tzinfo is None or not START<=at<END:return None
    matches=[s for s in stories or [] if exact_name(s.get('name'))==NAME]
    if len(matches)!=1:return None
    story=matches[0]
    if (story.get('key')!='SSReopen' or datetime.fromisoformat(story['start_utc'])!=START
            or datetime.fromisoformat(story['expire_utc'])!=END):return None
    markers=[s.get('stage') for s in story.get('stages',[]) if str(s.get('stage')).startswith('SSReopen-')]
    if markers!=['SSReopen-OS']:return None
    resource=Path(root)/'resource'
    tasks=json.loads((resource/'tasks/Stages/OS.json').read_text('utf-8-sig'))
    if (NAME not in tasks['OS-OpenOcr']['text'] or 'OSChapterToOS' not in tasks['OS-OpenOcr']['next']
            or '圣巡之旅' not in tasks['OSChapterToOS']['text']):return None
    tiles=(resource/'Arknights-Tile-Pos').resolve()
    index={}
    for row in json.loads((tiles/'overview.json').read_text('utf-8-sig')).values():
        if str(row.get('code','')).startswith('OS-'):
            index.setdefault((row['code'],row.get('stageId')),[]).append(row)
    stages=[];costs={}
    for section,suffix,ap in [('', '',(9,9,9,12,12,12,21,21,21,10)),
                              ('EX-','ex',(10,10,15,15,15,15,20,20)),
                              ('S-','s',(15,15,20,20,25))]:
        for n,cost in enumerate(ap,1):
            code=f'OS-{section}{n}';internal=f'act46side_{suffix}{n:02d}'
            spec=dict(display=code,internal=internal,modes=['normal'])
            ids=[internal]
            if code=='OS-EX-8':
                spec['challenge_internal']=internal+'#f#';ids.append(spec['challenge_internal'])
                spec['modes'].append('challenge')
            for i in ids:
                rows=index.get((code,i),[])
                if len(rows)!=1:return None
                tile=(tiles/rows[0]['filename']).resolve()
                if not tile.is_relative_to(tiles) or not tile.is_file():return None
                file=json.loads(tile.read_text('utf-8-sig'))
                if (file.get('code'),file.get('stageId'))!=(code,i):return None
            stages.append(spec);costs[code]=cost
    return dict(name=NAME,kind='rerun',stage_prefix='OS',start=START.astimezone().replace(tzinfo=None).isoformat(),
        end=END.astimezone().replace(tzinfo=None).isoformat(),entry_keywords=[NAME],
        combat_keywords=['圣巡之旅'],section_keywords=SECTIONS,task_keywords=['神谕谜题'],
        task_claim_enabled=True,stages=stages,sanity_costs=costs,replay_stages=list(costs),
        required_challenge_replays=['OS-EX-8'],task_clear_targets=[10,25,40],farm_stage=None,
        _discovery_status='ready_for_visual_navigation',_source='act46sre + current MAA SSReopen-OS + local tiles',
        _discovery_reason='复刻重打；进入对应篇章和关卡仍需实图确认')


@contextmanager
def boundary(app):
    previous=app.discover_event
    def discover(name,stories,maa_root,now=None):
        at=now or datetime.now(timezone.utc)
        row=calendar_identity(name,stories,at)
        if row and exact_name(row.get('name'))==NAME:
            try:event=profile(row['name'],[row],maa_root,at)
            except (KeyError,TypeError,ValueError,OSError):event=None
            if event:return event
        found=previous(name,stories,maa_root) if now is None else previous(name,stories,maa_root,now=now)
        return fallback_route(name,row,maa_root,at,found) if row else found
    with patch.object(app,'discover_event',discover):yield
