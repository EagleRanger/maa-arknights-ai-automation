"""Stage-milestone UI and exact, additive official map resource repair.

No game or MAA process is started by importing or preparing this module.
"""
import hashlib
import json
from pathlib import Path
import re
from unittest.mock import patch
import annihilation_rotation_v1 as v1

ORIGINAL_OBSERVE = v1.observe
ORIGINAL_AGREE = v1.agree
ROOT = Path(__file__).resolve().parent
OVERVIEW_URL = 'https://raw.githubusercontent.com/MaaAssistantArknights/MaaResource/main/resource/Arknights-Tile-Pos/overview.json'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def bundle_map(bundle, root=ROOT):
    row = bundle['overview_row']
    tile = (Path(root)/bundle['tile_path']).resolve()
    tile.relative_to(Path(root).resolve())
    if sha(tile) != bundle['tile_sha256']:
        raise ValueError('reviewed map resource changed')
    data = read(tile)
    for key in ('stageId', 'levelId', 'name', 'width', 'height'):
        if data[key] != row[key]:
            raise ValueError('map summary/geometry mismatch: ' + key)
    if row['stageId'] != bundle['stage_id'] or row['name'] != bundle['name']:
        raise ValueError('bundle map identity mismatch')
    return dict(stage_id=row['stageId'], name=row['name'], level_id=row['levelId'],
                tile=str(tile), tile_sha256=bundle['tile_sha256'])


def install_map(app, bundle, root=ROOT):
    """Add one reviewed official map, only with MAA closed. Preserve all others."""
    if app._maa_process_exists() is not False or app._maa_task_queue_running() is not False:
        raise ValueError('MAA must be closed before map resource installation')
    stage = bundle_map(bundle, root)
    folder = Path(app._maa_install_root())/'resource/Arknights-Tile-Pos'
    overview = folder/'overview.json'
    raw = overview.read_bytes(); data = json.loads(raw.decode('utf-8-sig'))
    row, key = bundle['overview_row'], bundle['overview_key']
    if any(value.get('stageId') == stage['stage_id'] and (k != key or value != row)
           for k, value in data.items()):
        raise ValueError('existing same-stage map differs; no overwrite')
    target = (folder/row['filename']).resolve()
    target.relative_to(folder.resolve())
    if target.exists() and sha(target) != stage['tile_sha256']:
        raise ValueError('existing map geometry differs; no overwrite')
    backup = Path(root)/'outputs/annihilation_resource_backups'/hashlib.sha256(raw).hexdigest()
    backup.mkdir(parents=True, exist_ok=True)
    saved = backup/'overview.json'
    if saved.exists() and saved.read_bytes() != raw:
        raise ValueError('resource backup conflict')
    saved.write_bytes(raw)
    if not target.exists():
        target.write_bytes(Path(stage['tile']).read_bytes())
    if key not in data:
        updated = dict(data); updated[key] = row
        temp = overview.with_suffix('.annihilation.tmp')
        temp.write_text(json.dumps(updated,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(overview)
    check = read(overview)
    if check[key] != row or any(check.get(k) != value for k,value in data.items()) or sha(target) != stage['tile_sha256']:
        raise ValueError('resource readback differs')
    return dict(status='verified',stage_id=stage['stage_id'],backup=str(saved),tile=str(target))


def proxy_locked(image, maa_root):
    """Positive MAA lock template match; no-match is NOT proof of unlocked."""
    import cv2
    import numpy as np
    folder=Path(maa_root)/'resource'
    tasks=read(folder/'tasks/tasks.json')
    rule=tasks['UnableToAgent2']
    files=list((folder/'template').rglob('UnableToAgent2.png'))
    if len(files)!=1:return False
    frame=cv2.imdecode(np.fromfile(str(image),np.uint8),cv2.IMREAD_COLOR)
    template=cv2.imdecode(np.fromfile(str(files[0]),np.uint8),cv2.IMREAD_COLOR)
    if frame is None or template is None:return False
    x,y,w,h=rule['roi']; crop=cv2.resize(frame,(1280,720))[y:y+h,x:x+w]
    if min(crop.shape[:2])==0 or crop.shape[0]<template.shape[0] or crop.shape[1]<template.shape[1]:return False
    scores=cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED)
    return bool(np.isfinite(scores).any() and float(np.nanmax(scores))>=.85)


def observe(items,maps,evidence,*,locked=False):
    result=ORIGINAL_OBSERVE(items,maps,evidence)
    if result['status']!='unknown' or not result.get('map'):
        return result
    text=v1.compact(' '.join(str(r[0]) for r in items))
    phases={int(n) for n in re.findall(r'阶段([0-8])/8(?!\d)',text)}
    if '作战进度' not in text or len(phases)!=1:
        return result
    phase=phases.pop()
    result.update(progress=dict(value=phase,max=8),proxy_lock_verified=locked)
    # Milestones are not literal kill counts, and may be unclaimed rewards.
    # Only a positive locked-proxy image corroborates the incomplete route.
    if phase<8 and locked:
        result.update(status='first_clear_required',kills=None,reason='milestones_incomplete_and_proxy_locked')
    else:
        result['reason']='milestone_progress_needs_exact_400_proof'
    return result


def remote_map(items, overview):
    """Exact observed name only; the online catalog never proves a clear."""
    text=v1.compact(' '.join(str(r[0]) for r in items))
    if '开始行动' not in text or '作战进度' not in text:
        return None
    matches=[]
    for row in overview.values():
        sid=row.get('stageId',''); name=v1.compact(row.get('name'))
        if re.fullmatch(r'camp_(?:r_)?\d+',sid) and name and name in text:
            matches.append(dict(stage_id=sid,name=name,level_id=row.get('levelId',''),
                overview_row=row,resource_source=OVERVIEW_URL,local_resource_missing=True))
    return matches[0] if len(matches)==1 else None


def agree(a,b):
    return ORIGINAL_AGREE(a,b) and a.get('progress')==b.get('progress')


class RuntimePort(v1.RuntimePort):
    def __init__(self,app,bundle=None):
        super().__init__(app)
        self.bundle=bundle
        if bundle:
            stage=bundle_map(bundle,Path(app.BASE))
            self.maps=[r for r in self.maps if r['stage_id']!=stage['stage_id']]+[stage]

    def _observe(self,items,maps,evidence):
        return observe(items,maps,evidence,locked=proxy_locked(evidence,self.app._maa_install_root()))

    def inspect(self):
        with patch.object(v1,'observe',self._observe),patch.object(v1,'agree',agree):
            result=super().inspect()
        if result['status']!='unknown':
            return result
        if not result.get('map') and result.get('reason')=='map_detail_not_unique':
            # Only the failed ordinary route reaches here. A new map missing
            # locally can still be identified and reported without AI browsing.
            path,items=self.frame('missing_map_detail')
            if '作战进度' in v1.compact(' '.join(r[0] for r in items)):
                overview=self.app._fetch_prts_json(OVERVIEW_URL)
                stage=remote_map(items,overview or {})
                if stage:
                    self.maps.append(stage)
                    first=self._observe(items,self.maps,path)
                    self.app.wait(1)
                    second_path,second_items=self.frame('missing_map_confirm')
                    second=self._observe(second_items,self.maps,second_path)
                    if agree(first,second):
                        second['before_evidence']=path
                        return second
                    result=first
        if not result.get('map'):
            return result
        # The exact-map detail is known, but its progress uses milestone bars.
        # Open only the observed progress label; do not guess a 400-kill result.
        path,items=self.frame('progress_detail')
        stage=result['map']; target=v1.unique_button(items,'作战进度')
        if not target or stage['name'] not in v1.compact(' '.join(r[0] for r in items)):
            return result
        self.app.tap(*target);self.app.wait(2)
        panel,rows=self.frame('progress_panel')
        anchors=[(stage['name'],1500,120),('开始行动',1700,980)]
        exact=ORIGINAL_OBSERVE(rows+anchors,[stage],panel)
        if exact['status']=='complete':
            self.app.wait(1);second_path,second_rows=self.frame('progress_panel_confirm')
            second=ORIGINAL_OBSERVE(second_rows+anchors,[stage],second_path)
            if ORIGINAL_AGREE(exact,second):
                second['map_binding_evidence']=path
                return second
        result.update(reason='progress_panel_400_unverified',evidence=panel,detail_evidence=path)
        return result

    def enter_formation(self,stage):
        with patch.object(v1,'observe',self._observe):
            return super().enter_formation(stage)

    def approved_job(self,stage):
        if not self.bundle or stage['stage_id']!=self.bundle['stage_id']:
            return super().approved_job(stage)
        path=Path(self.app.BASE)/self.bundle['job_path']
        data=read(path)
        if sha(path)!=self.bundle['job_sha256'] or not v1.job_matches(data,stage) or not data.get('actions'):
            raise ValueError('reviewed copilot mismatch')
        compatible,why=self.app._copilot_auto_compatibility(data)
        if not compatible:raise ValueError(why)
        return dict(path=str(path),sha256=sha(path),stage_id=stage['stage_id'],
                    source=self.bundle['job_source'],doc=data['doc'])
