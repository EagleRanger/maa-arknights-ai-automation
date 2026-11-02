"""TL normal-section bridge: official dates + pinned maps + live OCR navigation.

Does not invent upstream MAA navigation/calendar entries or stage completion.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from functools import lru_cache
import hashlib
import json
import shutil
import zipfile

ROOT=Path(__file__).resolve().parent
ARCHIVE=ROOT/'assets/maa_tl_20261101/MaaResource-TL-subset.zip'
# Rebuilt source-format subset; upstream archive + individual hashes in PROVENANCE.json.
ARCHIVE_SHA='34510776BC79138294EBF083D092ECB3462D0217CC2DD2644FC7A57794E1611C'
NAME='时间啊，向前！'
START='2026-11-01T12:00:00+08:00'
END='2026-11-22T03:59:00+08:00'
ANNOUNCEMENT='https://ak.hypergryph.com/news/0787'
FARM=[('TL-7','31043','半自然溶剂'),('TL-8','31083','环烃聚质'),('TL-9','31113','电极单元')]

def active(at=None):
    at=at or datetime.now().astimezone()
    if at.tzinfo is None:raise ValueError('timezone-aware activity clock required')
    return datetime.fromisoformat(START)<=at<datetime.fromisoformat(END)

@lru_cache(maxsize=1)
def maps(archive=ARCHIVE):
    if hashlib.sha256(Path(archive).read_bytes()).hexdigest().upper()!=ARCHIVE_SHA:
        raise ValueError('official TL archive fingerprint drift')
    with zipfile.ZipFile(archive) as z:
        overview=json.loads(z.read('MaaResource-main/resource/Arknights-Tile-Pos/overview.json'))
        rows={k:v for k,v in overview.items() if v.get('stageId','').startswith('act55side_')}
        by_code={r['code']:r for r in rows.values()}
        if not all(f'TL-{n}' in by_code for n in range(1,11)):
            raise ValueError('normal TL map set incomplete')
        result=[]
        for key,row in rows.items():
            data=z.read('MaaResource-main/resource/Arknights-Tile-Pos/'+row['filename'])
            tile=json.loads(data)
            if tile['stageId']!=row['stageId'] or tile['code']!=row['code']:
                raise ValueError('TL tile identity conflict')
            result.append((key,row,data))
        return result

def prepare_maps(root):
    """Use before MAA starts; merge only the 11 pinned TL maps, keep overlays."""
    from dp_resource_integrity_v36 import _atomic_json
    from dp_event_route_v26 import _atomic_bytes
    dest=Path(root)/'resource/Arknights-Tile-Pos'
    overview_path=dest/'overview.json'
    current=json.loads(overview_path.read_text('utf-8-sig'))
    changed=[]
    overview_changed=False
    for key,row,data in maps():
        target=dest/row['filename']
        if key in current and current[key]!=row:
            raise ValueError('conflicting existing TL overview')
        if target.exists() and target.read_bytes()!=data:
            raise ValueError('conflicting existing TL map')
        if not target.exists():
            _atomic_bytes(target,data);changed.append(row['code'])
        overview_changed=overview_changed or current.get(key)!=row
        current[key]=row
    if changed or overview_changed:
        backup=ROOT/'outputs/maa_resource_backups'/('overview.before_tl_'+hashlib.sha256(overview_path.read_bytes()).hexdigest()[:16]+'.json')
        backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():shutil.copy2(overview_path,backup)
        _atomic_json(overview_path,current)
    return dict(source='official MaaResource pinned TL subset',changed=changed)

def profile(name,root,at=None):
    import event_availability_v12 as availability
    if availability.exact_name(name)!=availability.exact_name(NAME) or not active(at):return None
    rows=maps()
    for key,row,data in rows:
        target=Path(root)/'resource/Arknights-Tile-Pos'/row['filename']
        if not target.is_file() or target.read_bytes()!=data:return None
    return dict(name=NAME,kind='new',start=START,end=END,stage_prefix='TL',
        entry_keywords=[NAME],combat_keywords=['残照终尽'],section_keywords={'normal':['残照终尽']},
        stages=[dict(display=f'TL-{n}',internal=f'act55side_{n:02d}',modes=['normal']) for n in range(1,11)],
        tutorial_stages=[dict(display='TL-TR-1',internal='act55side_tr01',modes=['normal'])],
        story_stages=[f'TL-ST-{n}' for n in range(1,5)],first_clear_modes=['normal'],farm_stage=None,
        manual_prerequisites=[dict(display='TL-TR-1',before='TL-1',kind='tutorial')],
        task_keywords=['晨曦所见证的'],
        pending_sections=[dict(name='长冬初青',opens_at='2026-11-08T16:00:00+08:00'),
                          dict(name='世纪之春',opens_at='2026-11-15T16:00:00+08:00')],
        _discovery_status='ready_for_visual_navigation',
        _discovery_reason='官方公告、MaaResource地图身份已确认；仍须实图核验导航/通关，不伪造MAA日历',
        _source='official TL announcement + pinned MaaResource + live terminal',
        announcement=ANNOUNCEMENT)

def augment_tip(tip,at=None):
    """Separate primary drop metadata from the fresh complete inventory proof."""
    if not active(at):return tip
    result=deepcopy(tip)
    depot=result.get('depot') or {}
    complete=False
    try:
        raw=json.loads(Path(result['source']['depot']).read_text('utf-8-sig'))
        complete=(depot.get('fresh') is True and raw.get('done') is True
                  and isinstance(raw.get('data'),dict) and bool(raw['data'])
                  and datetime.fromisoformat(raw['syncTime'])==datetime.fromisoformat(depot['sync_time']))
    except (OSError,ValueError,KeyError,TypeError):pass
    stages=[]
    for code,item,name in FARM:
        count=(depot.get('counts') or {}).get(item,0) if complete else None
        if type(count) is not int or count<0:count=None
        stages.append(dict(stage=code,drop_id=item,drop=name,inventory=count,
            source='game stage_table act55side displayDetailRewards NORMAL/MATERIAL',
            inventory_basis='matching_fresh_done_depot' if complete else 'unverified'))
    story=dict(key='TL',name=NAME,start_utc=START,expire_utc=END,stages=stages,
        source=ANNOUNCEMENT,calendar_origin='official_announcement_not_upstream_MAA_cache')
    result['active_side_stories']=[story,*[s for s in result.get('active_side_stories',[]) if s.get('name')!=NAME]]
    return result

@contextmanager
def boundary(app):
    import daily_portable_bootstrap_v1 as bootstrap
    original_paths=bootstrap.resource_paths
    original_discover=app.discover_event
    original_tip=app.build_maa_daily_stage_tip
    original_first=app.mode_event_first_clear
    @contextmanager
    def paths(*args,**kwargs):
        with original_paths(*args,**kwargs) as info:
            print('ARK_TL_MAPS '+json.dumps(prepare_maps(info['root']),ensure_ascii=False),flush=True)
            yield info
    def discover(name,stories,maa_root,now=None):
        admitted=profile(name,maa_root,now)
        return admitted or original_discover(name,stories,maa_root,now=now)
    def tip(*args,**kwargs):
        return augment_tip(original_tip(*args,**kwargs),kwargs.get('now'))
    def first(event=None):
        event=event or app.get_active_event()
        if (event or {}).get('stage_prefix')=='TL' and app.goto_event_map(event):
            frame=str(app.shot('tl_first_prerequisite'))
            rows=app.ocr(frame)
            manual=app._visible_event_manual_prerequisites(rows,event,'TL-1')
            if manual and not app._event_stage_position(rows,'TL-1'):
                prerequisite=next(iter(manual))
                app._record_event_manual_prerequisite(event,'TL-1',prerequisite,evidence_path=frame)
                return ('manual_required',prerequisite)
        return original_first(event)
    with patch.object(bootstrap,'resource_paths',paths),patch.object(app,'discover_event',discover), \
         patch.object(app,'build_maa_daily_stage_tip',tip),patch.object(app,'mode_event_first_clear',first):
        yield
