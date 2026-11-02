"""Public synthetic V146 profile probe, with no account screenshots or startup.

Loads only the exact pure badge function by AST, then the profile definitions
without importing either business entrypoint. This is NOT a full daily-graph
probe, a real OCR test, or natural-gameplay acceptance.
"""
import ast
import dataclasses
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
import unicodedata
from typing import Callable
from PIL import Image, ImageDraw


def profile_module(root):
    badge_tree = ast.parse((root/'arknights_daily_runtime_v12.py').read_text('utf-8-sig'))
    selected = [node for node in badge_tree.body
                if isinstance(node, ast.FunctionDef) and node.name == '_event_normal_badges_ratio']
    assert len(selected) == 1
    pure = {}
    exec(compile(ast.Module(body=selected,type_ignores=[]),'pure_native_badge_function','exec'),pure)
    module = ModuleType('public_synthetic_layout_profile')
    # Pure helper modules have no app startup; import only the cost reader.
    sys.path.insert(0,str(root))
    from stage_sanity_cost_v2 import read_cost
    module.__dict__.update(dataclass=dataclasses.dataclass,re=re,unicodedata=unicodedata,
                           Callable=Callable,Image=Image,normal_cost=read_cost,
                           ordinary_badges=pure['_event_normal_badges_ratio'])
    def not_exercised(*args):
        raise AssertionError('Special historical reader intentionally not exercised by synthetic probe')
    module.__dict__.update(yw_cost=not_exercised,yw_badge_ratio=not_exercised)
    sys.modules[module.__name__]=module
    tree=ast.parse((root/'event_layout_profiles_v1.py').read_text('utf-8-sig'))
    tree.body=[n for n in tree.body if not isinstance(n,(ast.Import,ast.ImportFrom))]
    exec(compile(tree,'event_layout_profiles_v1.py (pure definitions only)','exec'),module.__dict__)
    return module


def main(root=None):
    root=Path(root).resolve() if root else Path(__file__).resolve().parents[1]
    L=profile_module(root)
    rows=[('ZZ-7',1447,144),('代理指挥',1777,889),('开始行动',1766,986),('-21',1812,1031)]
    event=dict(name='Synthetic activity',kind='new',stage_prefix='ZZ',
               stages=[dict(display='ZZ-7',internal='synthetic_normal_07',modes=['normal'])])
    checks=[]
    def check(name,condition):
        assert condition,name
        checks.append(name)
    with TemporaryDirectory(prefix='ark-public-layout-') as temporary:
        frame=Path(temporary)/'synthetic.png'
        image=Image.new('RGB',(1920,1080),(15,15,15)); draw=ImageDraw.Draw(image)
        for center in (.815,.861,.905):
            draw.rectangle((int(1920*(center-.017)),int(1080*.128),
                            int(1920*(center+.017)),int(1080*.195)),fill=(20,200,240))
        image.save(frame)
        obs=L.inspect_frame(frame,rows,event,'ZZ-7')
        check('normal_profile',obs['profile']==L.ORDINARY.key)
        check('synthetic_three_badges',L.PROFILES[obs['profile']].badges(frame)>.99)
        check('current_single_price',L.price(obs,frame,rows,None)['unit_cost']==21)
        draw.rectangle((int(1920*(.905-.017)),int(1080*.128),
                        int(1920*(.905+.017)),int(1080*.195)),fill=(15,15,15));image.save(frame)
        check('two_badges_not_three',L.PROFILES[obs['profile']].badges(frame)==0)
        wrong=L.identify(rows,expected='ZZ-8',event=event)
        check('wrong_target_refused',wrong['reason']=='target_mismatch' and L.price(wrong,frame,rows,None) is None)
        ambiguous=L.identify(rows+[('XX-1',1500,150)],expected='ZZ-7',event=event)
        check('ambiguous_header_refused',ambiguous['reason']=='ambiguous_or_missing_detail_header')
        challenge=L.identify(rows+[('附加条件',1650,500)],expected='ZZ-7',event=event)
        check('challenge_refused',challenge['reason']=='not_normal_farm_mode')
        check('wrong_activity_refused',L.identify(rows,expected='ZZ-7',event=dict(event,stage_prefix='XX'))['reason']=='activity_mismatch')
        check('missing_catalog_refused',L.identify(rows,expected='ZZ-7',event=dict(event,stages=[]))['reason']=='activity_stage_not_unique_or_not_normal')
        Image.new('RGB',(960,540)).save(frame)
        check('wrong_geometry_refused',L.inspect_frame(frame,rows,event,'ZZ-7')['reason']=='unsupported_frame_geometry')
    print(json.dumps(dict(status='passed',checks=checks,game_actions=0,
                          business_entrypoints_imported=False,source='generated_synthetic_frame',
                          scope='profile_identity_price_badges_negative_guards_only',
                          not_verified=['real OCR','full daily assembly','natural gameplay','special historical readers']),ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':
    raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else None))
