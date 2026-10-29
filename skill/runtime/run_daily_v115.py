"""Candidate V115: exact V114 game binding plus preview sign-in receipt loop."""
from datetime import datetime
from unittest.mock import patch
import argparse
import json
import sys
import run_daily_v113 as previous
import run_daily_v111 as identity_check
from run_daily_v103 import ROOT, read, sha
from daily_runtime_target_v1 import boundary as target_boundary, inventory
from event_signin_preview_v7 import boundary as signin_boundary

ENTRYPOINT = 'run_daily_v115.py --mode full'


def check_entry(at=None, packet=None):
    with patch.object(identity_check, 'ENTRYPOINT', ENTRYPOINT), patch.object(identity_check, '__file__', __file__):
        result = identity_check.check_entry(at, packet)
    if packet and (packet.get('workflow') != 'ARK-DAILY-STABLE-V115' or
                   packet.get('entrypoint') != ENTRYPOINT or packet['artifacts'].get('run_daily_v115.py') != sha(__file__)):
        raise ValueError('V115_candidate_binding_mismatch')
    import arknights_daily_runtime_v12 as app
    result['game_runtime_target'] = inventory(app.MUMU_CLI)
    return result


def full(packet=None):
    import arknights_daily_runtime_v12 as app
    import daily_workflow_identity_v1 as identity
    old = identity.boundary
    h = read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json')
    binding = dict(workflow='ARK-DAILY-STABLE-V115', entrypoint=ENTRYPOINT,
        handoff_id=packet['handoff_id'] if packet else h['handoff_id'], sha256=sha(__file__))
    with target_boundary(app), signin_boundary(), \
         patch.object(identity, 'boundary', lambda runtime, root, ignored: old(runtime, root, binding)), \
         patch.object(previous, 'check_entry', lambda at=None, packet=None: check_entry(at, packet)):
        return previous.full(packet)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['full'], default='full')
    parser.add_argument('--handoff')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    packet = read(args.handoff) if args.handoff else None
    check_entry(packet=packet)
    if args.check_only:
        print('PASS V115; game actions0')
        return 0
    if packet:
        latch = (ROOT/packet['dispatch_latch']).resolve()
        latch.relative_to(ROOT/'outputs/continuations')
        with latch.open('x', encoding='utf-8') as stream:
            json.dump(dict(handoff=packet['handoff_id'], at=datetime.now().astimezone().isoformat()), stream)
    sys.argv = [str(ROOT/'run_daily.py'), '--mode', 'full']
    return full(packet)


if __name__ == '__main__':
    raise SystemExit(main())
