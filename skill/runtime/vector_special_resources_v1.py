"""Pinned VEC#3 tile subset; reuse proven seven-field overview/atomic writers."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
from dp_resource_integrity_v36 import _entry_from_payload, _atomic_json
from dp_event_route_v26 import _atomic_bytes

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()

def verified_candidates(project_root, manifest_path):
    root=Path(project_root).resolve()
    manifest_path=Path(manifest_path).resolve()
    manifest_path.relative_to(root)
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('status')!='offline_candidates_verified' or manifest.get('game_actions')!=0:
        raise ValueError('Candidate manifest not verified')
    rows=[]
    for row in manifest['stages']:
        tile_path=(root/row['tile_path']).resolve()
        job_path=(root/row['job_path']).resolve()
        for p in (tile_path,job_path):
            p.relative_to(root)
        if digest(tile_path)!=row['tile_sha256'] or digest(job_path)!=row['job_sha256']:
            raise ValueError('Candidate fingerprint changed')
        tile=json.loads(tile_path.read_text(encoding='utf-8'))
        job=json.loads(job_path.read_text(encoding='utf-8'))
        if (tile['stageId']!=row['internal_stage'] or tile['code']!=row['code'] or tile['name']!=row['name']
                or job['stage_name']!=tile['stageId'] or not job.get('actions')):
            raise ValueError('Stage identity mismatch')
        entry=_entry_from_payload(tile,tile_path.name)
        key=tile['stageId']+'-'+tile['levelId']
        rows.append((row,tile_path,key,entry))
    return rows

def install(project_root, maa_root, manifest_path, *, queue_idle):
    # The execution owner supplies an actual idle check, never a fixed bool.
    if not queue_idle():
        raise RuntimeError('MAA queue owns controller; resource write forbidden')
    rows=verified_candidates(project_root,manifest_path)
    resource=Path(maa_root)/'resource/Arknights-Tile-Pos'
    overview_path=resource/'overview.json'
    overview=json.loads(overview_path.read_text(encoding='utf-8-sig'))
    updates={key:entry for _,_,key,entry in rows}
    ready=all(overview.get(key)==entry and (resource/p.name).is_file()
              and digest(resource/p.name)==row['tile_sha256'] for row,p,key,entry in rows)
    if ready:
        return {'status':'ready','changed':False,'stages':[r[0]['code'] for r in rows]}
    backup=Path(maa_root)/'.codex-resource-backups'/('vector-sp-v1-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True,exist_ok=False)
    shutil.copy2(overview_path,backup/'overview.json')
    existing=set()
    for _,p,_,_ in rows:
        target=resource/p.name
        if target.exists():
            existing.add(p.name)
            shutil.copy2(target,backup/p.name)
    try:
        if not queue_idle():
            raise RuntimeError('Queue became active before first write')
        for row,p,_,_ in rows:
            _atomic_bytes(resource/p.name,p.read_bytes())
            if digest(resource/p.name)!=row['tile_sha256']:
                raise ValueError('Resource readback failed')
        overview.update(updates)
        _atomic_json(overview_path,overview)
        actual=json.loads(overview_path.read_text(encoding='utf-8-sig'))
        assert all(actual[key]==entry for key,entry in updates.items())
        return {'status':'ready','changed':True,'backup':str(backup),'stages':[r[0]['code'] for r in rows]}
    except BaseException:
        shutil.copy2(backup/'overview.json',overview_path)
        for _,p,_,_ in rows:
            target=resource/p.name
            if p.name in existing:
                shutil.copy2(backup/p.name,target)
            else:
                target.unlink(missing_ok=True)
        raise
