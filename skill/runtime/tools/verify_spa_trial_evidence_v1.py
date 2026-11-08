"""Read-only replay of one recorded SPA trial; never opens or clicks the game."""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ark_host.cooperation_v1 import atomic_json
from spa_core_trial_v1 import is_lobby_event
from spa_rewards_state_v1 import observe
from local_ocr_v6_small_v2 import reader


def audit_callbacks(events):
    lobby=False; errors=[]; completed=False
    for e in events:
        msg,detail=e['msg'],e['details']
        lobby=lobby or is_lobby_event(msg,detail)
        if detail.get('taskchain')=='Custom':
            if msg in (10000,10004):errors.append(e)
            if msg==10002:
                completed=True;break  # Later AsstStop is lifecycle, not failure.
    return dict(native_completed=completed,lobby_action=lobby,errors_before_completion=errors,
                native_cycle_verified=completed and lobby and not errors)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    out=(ROOT/a.output).resolve();out.relative_to(ROOT/'outputs')
    receipt=json.loads((out/'receipt.json').read_text(encoding='utf-8'))
    checks=[]
    for result in receipt['module_results']:
        path=Path(result['callbacks']);path.resolve().relative_to(out)
        check=audit_callbacks(json.loads(s) for s in path.read_text(encoding='utf-8').splitlines())
        checks.append(dict(check,callbacks=str(path),original_result=result))
    pages=[]
    with reader() as engine:
        app=SimpleNamespace(_ocr_engine=engine)
        for row in receipt['frames']:
            state=observe(app,row['screenshot'],row['items'])
            if state['page']!='unknown':pages.append(dict(seq=row['seq'],path=row['screenshot'],**state))
    result=dict(read_only_replay=True,raw_receipt_preserved=True,callbacks=checks,pages=pages,
                purchases=0,claims_verified=0,cleanup=receipt.get('cleanup'),
                controller_released=receipt.get('controller_released'))
    atomic_json(out/'evidence_replay.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
