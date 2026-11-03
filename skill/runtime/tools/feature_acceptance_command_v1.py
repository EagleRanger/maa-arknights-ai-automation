import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from feature_acceptance_transport_v1 import submit,ACTIONS

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--action',choices=sorted(ACTIONS),required=True)
    p.add_argument('--point',nargs=2,type=int);p.add_argument('--start',nargs=2,type=int);p.add_argument('--end',nargs=2,type=int)
    p.add_argument('--job');p.add_argument('--service');p.add_argument('--reason');p.add_argument('--wait',type=float)
    args=p.parse_args();data={k:v for k,v in vars(args).items() if k!='output' and v is not None}
    out=(ROOT/args.output).resolve();out.relative_to(ROOT/'outputs')
    print(json.dumps({'command':str(submit(out,data))},ensure_ascii=False))

if __name__=='__main__':main()
