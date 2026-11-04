"""Resume only unfinished daily modules through the currently selected release."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import argparse
import hashlib
import importlib
import json
import sys
from daily_dispatch_v1 import ROOT, read, resolve, preflight, selected_scope
from daily_final_tail_scope_v1 import run_scope


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def admit(path, *, check=True):
    path=Path(path).resolve();path.relative_to(ROOT/'outputs/continuations')
    packet=read(path);h=read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json')
    bound=h.get('current_daily_continuation') or {}
    if (bound.get('scope')!='final_daily_only' or (ROOT/bound['handoff']).resolve()!=path
            or bound.get('handoff_sha256')!=sha(path) or packet.get('scope')!='final_daily_only'
            or packet.get('resources')!='no_stamina_battles_no_refills'):
        raise ValueError('current final-only continuation identity mismatch')
    source_path=(ROOT/packet['source_manifest']).resolve()
    source_path.relative_to(ROOT/'outputs/run_manifests')
    source=read(source_path)
    if (source.get('run_id')!=packet['source_run_id'] or sha(source_path)!=packet['source_sha256']
            or source.get('status')!='partial_or_blocked' or not source.get('cleanup_verified')):
        raise ValueError('source effects not sealed')
    now=datetime.now().astimezone()
    if ((datetime.fromisoformat(source['started_at'])-timedelta(hours=4)).date()
            != (now-timedelta(hours=4)).date()):
        raise ValueError('continuation game day changed')
    selected=resolve(h)
    return packet,source,selected,preflight(selected) if check else None


def execute(packet,source,selected,checked):
    import run_daily as base
    import arknights_daily_runtime_v12 as app
    entry=importlib.import_module(selected['module'])
    from continuation_report_v2 import boundary as reports
    original_main=base.main
    def main(*a,**k):
        with patch.object(base,'run_scope',lambda port:run_scope(port,packet)):
            return original_main(*a,**k)
    sys.argv=[str(ROOT/'run_daily.py'),'--mode','full','--run-id',packet['run_id'],'--existing-sanity-only']
    with reports(ROOT,packet,source),selected_scope(selected,checked),patch.object(base,'main',main):
        return entry.full()


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--handoff',required=True);p.add_argument('--check-only',action='store_true')
    a=p.parse_args(argv);packet,source,selected,checked=admit(a.handoff)
    if a.check_only:
        print(json.dumps(dict(status='PASS',scope=packet['scope'],entrypoint=selected['entrypoint'],game_actions=0)))
        return 0
    latch=(ROOT/packet['dispatch_latch']).resolve();latch.relative_to(ROOT/'outputs/continuations')
    with latch.open('x',encoding='utf-8') as stream:
        json.dump(dict(handoff=packet['handoff_id'],at=datetime.now().astimezone().isoformat()),stream)
    return execute(packet,source,selected,checked)


if __name__=='__main__':raise SystemExit(main())
