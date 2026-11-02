"""Explicit receiver-only collection; no screenshot capture or game/application start.

Full frames are read locally but never copied. Only the documented tiny crop and
its fingerprint are kept. Do not distribute recipient_resources or local manifest.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from portable_resources_v1 import VISUAL_RECIPES, BASE_NOTIFICATION_SHA, local_visual_path

def collect(key, source, *, root=ROOT):
    from PIL import Image
    source = Path(source)
    root = Path(root)
    size,box = VISUAL_RECIPES[key]
    destination = root/'recipient_resources/visual'/(key+'.png')
    with Image.open(source) as frame:
        if frame.size != size:
            raise ValueError('expected source dimensions '+str(size))
        crop = frame.convert('RGB').crop(box)
    if key == 'base_notification' and hashlib.sha256(source.read_bytes()).hexdigest().upper() != BASE_NOTIFICATION_SHA:
        raise ValueError('installed MAA notification template differs from the inspected upstream template')
    if destination.exists():
        raise ValueError('local resource exists; preserve it and review before replacing')
    manifest_path = root/'config/local_visual_resources_v1.json'
    data = json.loads(manifest_path.read_text('utf-8')) if manifest_path.exists() else dict(
        schema='local_visual_resources_v1',resources={})
    if data.get('schema') != 'local_visual_resources_v1':
        raise ValueError('unknown existing local manifest schema')
    destination.parent.mkdir(parents=True,exist_ok=True)
    if key == 'base_notification':
        shutil.copyfile(source,destination)  # Preserve upstream's pinned PNG bytes.
    else:
        crop.save(destination,format='PNG')
    digest = hashlib.sha256(destination.read_bytes()).hexdigest().upper()
    data['resources'][key] = dict(sha256=digest,size=list(crop.size),crop=list(box),
        source='recipient_installed_MAA' if key == 'base_notification' else 'recipient_supplied_frame',
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest().upper())
    manifest_path.parent.mkdir(parents=True,exist_ok=True)
    manifest_path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if local_visual_path(key,root=root) != destination.resolve():
        raise ValueError('local crop readback failed')
    return dict(key=key,size=list(crop.size),sha256=digest,status='collected_not_game_validated')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind',required=True,choices=sorted(VISUAL_RECIPES))
    parser.add_argument('--source',required=True,type=Path,
                        help='Your own matching screenshot; base_notification takes your installed MAA template')
    args = parser.parse_args()
    print(json.dumps(collect(args.kind,args.source),ensure_ascii=False))

if __name__ == '__main__':
    main()
