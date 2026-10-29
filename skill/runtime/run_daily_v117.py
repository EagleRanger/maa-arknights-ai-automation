"""Normal daily candidate: V116 host + stage milestones / missing-map intake."""
from unittest.mock import patch
import run_daily_v116 as previous
from annihilation_rotation_v1 import boundary as weekly_boundary
from annihilation_rotation_v2 import RuntimePort

ENTRYPOINT='run_daily_v117.py --mode full'
COMPONENT='ARK-ANNIHILATION-ROTATION-V2-CANDIDATE'


def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):
        return previous.check_entry(at,packet)


def full():
    with patch.object(previous,'COMPONENT',COMPONENT),patch.object(previous,'ENTRYPOINT',ENTRYPOINT), \
         patch.object(previous,'__file__',__file__), \
         patch.object(previous,'boundary',lambda app:weekly_boundary(app,RuntimePort)):
        return previous.full()


def main(argv=None):
    import argparse,sys
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['full'],default='full')
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv)
    if args.check_only:
        check_entry();print('PASS V117 candidate; game actions0');return 0
    sys.argv=[str(previous.ROOT/'run_daily.py'),'--mode','full']
    return full()


if __name__=='__main__':raise SystemExit(main())
