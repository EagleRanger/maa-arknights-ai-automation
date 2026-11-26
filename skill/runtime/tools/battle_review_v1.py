"""Attach a verified game outcome or tactical observation from an existing AI trial.

File-only bridge for a live or already-loaded MAA host. Does not start the
game, take control, force a retry or require the original Python to restart.
"""
import argparse
import json
from pathlib import Path
from shutil import copyfile
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from battle_incident_v1 import Review


def main(argv=None):
    p=argparse.ArgumentParser()
    for k in ('mode','account','difficulty','stage','strategy','attempt','detail'):
        p.add_argument('--'+k,required=True)
    p.add_argument('--event',choices=['confirmed_defeat','confirmed_leak','suspected_leak',
        'deployment','cause_verified','victory','planned_exit','technical_error'],required=True)
    p.add_argument('--frame',type=Path)
    a=p.parse_args(argv)
    r=Review(ROOT,account=a.account,mode=a.mode,difficulty=a.difficulty,stage=a.stage,strategy=a.strategy)
    def picture(path):
        src=a.frame.resolve(strict=True)
        if not src.is_relative_to(ROOT) or src.suffix.lower()!='.png':
            raise ValueError('expected current project PNG')
        copyfile(src,path)
    take=picture if a.frame else None
    if a.event=='confirmed_defeat':saved=r.result(a.attempt,a.event,picture=take,detail=a.detail)
    elif a.event in ('victory','planned_exit','technical_error'):saved=False
    else:saved=r.observe(a.attempt,{'confirmed_leak':'已核实漏怪','suspected_leak':'疑似漏怪',
        'deployment':'关键部署','cause_verified':'已核实败因'}[a.event],picture=take,detail=a.detail)
    print(json.dumps(dict(failed_attempts=len(r.data['failed_attempts']),review_active=r.active,
        new_observation=saved,review=str(r.dir/'复盘.md') if r.active else None),ensure_ascii=False))


if __name__=='__main__':main()
