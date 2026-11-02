"""Keep installed TL map updates; validate identity instead of old byte equality."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import hashlib
import json
import event_tl_route_v1 as prior
import event_tl_route_v2 as date_adapter


def installed_maps(root):
    dest = (Path(root) / 'resource/Arknights-Tile-Pos').resolve()
    overview = json.loads((dest/'overview.json').read_text('utf-8-sig'))
    result = []
    for key, expected, _ in prior.maps():
        row = overview.get(key)
        if row is None:
            return None  # Old versions can still use the pinned missing-map bridge.
        if row.get('stageId') != expected['stageId'] or row.get('code') != expected['code']:
            raise ValueError('installed TL overview identity mismatch')
        path = (dest / row['filename']).resolve()
        if not path.is_relative_to(dest) or path.suffix.lower() != '.json':
            raise ValueError('installed TL map outside resource root')
        if not path.is_file():
            return None
        data = path.read_bytes()
        tile = json.loads(data)
        if tile.get('stageId') != row['stageId'] or tile.get('code') != row['code']:
            raise ValueError('installed TL tile identity mismatch')
        if not isinstance(tile.get('tiles'), list) or not tile['tiles']:
            raise ValueError('installed TL tile grid missing')
        result.append((key,row,data))
    return result


@contextmanager
def boundary():
    old_prepare, old_profile = prior.prepare_maps, prior.profile
    def prepare(root):
        rows = installed_maps(root)
        if rows is None:
            return old_prepare(root)
        return dict(source='installed_TL_maps_identity_verified_no_overwrite', changed=[],
            preserved=[dict(code=row['code'], sha256=hashlib.sha256(data).hexdigest()) for _,row,data in rows])
    def profile(name,root,at=None):
        rows = installed_maps(root)
        if rows is None:
            return old_profile(name,root,at)
        with patch.object(prior,'maps',return_value=rows):
            return old_profile(name,root,at)
    # V2 installs later and calls its import-time alias, not prior.profile.
    # Patch that actual consumer too; otherwise the old byte guard reappears.
    with patch.object(prior,'prepare_maps',prepare), patch.object(prior,'profile',profile), \
         patch.object(date_adapter,'ORIGINAL_PROFILE',profile):
        yield
