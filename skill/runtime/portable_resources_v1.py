"""Fail-closed references acquired on the receiving PC, never author screenshots.

Only explicit local collection writes these files. Runtime loading never captures,
downloads, installs or accepts an unpinned/oversized reference.
"""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent
LOCAL_MANIFEST = ROOT/'config/local_visual_resources_v1.json'
VISUAL_RECIPES = {
    'signin_folded_v6': ((1920,1080),(0,137,20,180)),
    'signin_expanded_v6': ((1920,1080),(373,49,444,86)),
    'signin_folded_v7': ((1920,1080),(26,195,108,230)),
    'workshop_zero': ((1920,1080),(1525,315,1595,370)),
    'workshop_mood8': ((1920,1080),(1725,315,1810,370)),
    'trust_ascending': ((1920,1080),(1550,60,1600,90)),
    'maa_home_2791': ((1280,720),(286,387,315,411)),
    'maa_home_entry_infrast': ((1280,720),(941,554,1033,616)),
    'maa_home_entry_recruit': ((1280,720),(978,474,1115,524)),
    'maa_home_entry_mall': ((1280,720),(778,458,893,511)),
    'maa_home_entry_task': ((1280,720),(737,538,825,606)),
    'maa_home_entry_depot': ((1280,720),(1151,592,1221,632)),
    'maa_home_entry_friends': ((1280,720),(356,539,413,573)),
    'maa_home_entry_terminal': ((1280,720),(915,143,1034,213)),
    'base_notification': ((61,42),(0,0,61,42)),
}
BASE_NOTIFICATION_SHA = '1D41DC2F6ACFF51DF647653EB3AF592900E366DF39C613C51B11394F27D5FCBF'

def local_visual_path(key, *, root=ROOT):
    """Return a pinned minimal local crop, or None; no reference means no click."""
    from PIL import Image
    if key not in VISUAL_RECIPES:
        raise ValueError('unknown local visual recipe')
    root = Path(root).resolve()
    path = root/'recipient_resources/visual'/(key+'.png')
    try:
        manifest = json.loads((root/'config/local_visual_resources_v1.json').read_text('utf-8'))
        if manifest.get('schema') != 'local_visual_resources_v1':
            return None
        row = manifest.get('resources',{}).get(key,{})
        digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        if digest != row.get('sha256') or row.get('source') not in {
                'recipient_supplied_frame','recipient_installed_MAA'}:
            return None
        _,box = VISUAL_RECIPES[key]
        expected = (box[2]-box[0],box[3]-box[1])
        with Image.open(path) as image:
            if image.size != expected or image.format != 'PNG':
                return None
            image.verify()
        if key == 'base_notification' and digest != BASE_NOTIFICATION_SHA:
            return None
        return path
    except (OSError,ValueError,TypeError,AttributeError):
        return None
