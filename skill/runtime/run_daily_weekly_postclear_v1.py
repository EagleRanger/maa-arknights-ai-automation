"""One bounded continuation: first-clear rewards, weekly deficit, sanity, tail."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from unittest.mock import patch
import run_daily_weekly_repair_v2 as host
from run_daily_v103 import ROOT, read, sha, check_entry as BASE_CHECK
from daily_weekly_postclear_v1 import run_scope

WORKFLOW = 'ARK-WEEKLY-POSTCLEAR-V1'


def check_entry(at=None, packet=None):
    if not packet or packet.get('workflow') != WORKFLOW or packet.get('scope') != 'saved_400_rewards_weekly_remaining_stamina_post_daily':
        raise ValueError('postclear scope missing')
    if packet.get('resources') != 'existing_sanity_only_no_refills':
        raise ValueError('resources differ')
    result = BASE_CHECK(at, packet)
    source = read(ROOT/packet['source_manifest'])
    clear = packet['saved_clear']
    if sha(ROOT/packet['source_manifest']) != packet['source_sha256'] or source.get('cleanup_verified') is not True:
        raise ValueError('source effects unsettled')
    if (clear['source_run_id'] != source['run_id'] or clear['stage_id'] != packet['stage_id']
            or clear['kills'] != 400 or clear['leaked'] != 0 or clear['defense'] <= 0
            or clear['saved'] is not True or not clear.get('before') or not clear.get('after')):
        raise ValueError('saved real 400 evidence missing')
    return result


def full(packet, source, bundle):
    with patch.object(host, 'WORKFLOW', WORKFLOW), patch.object(host, '__file__', __file__), \
         patch.object(host, 'check_entry', check_entry), patch.object(host, 'run_scope', run_scope):
        return host.full(packet, source, bundle)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--handoff', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    path = Path(args.handoff).resolve(); path.relative_to(ROOT/'outputs/continuations')
    packet = read(path); check_entry(packet=packet)
    if args.check_only:
        print('PASS saved-400 continuation; game actions0'); return 0
    latch = ROOT/packet['dispatch_latch']; latch.resolve().relative_to(ROOT/'outputs/continuations')
    with latch.open('x', encoding='utf-8') as stream:
        json.dump(dict(handoff=packet['handoff_id'], at=datetime.now().astimezone().isoformat()), stream)
    sys.argv = [str(ROOT/'run_daily.py'), '--mode', 'full', '--existing-sanity-only']
    return full(packet, read(ROOT/packet['source_manifest']), read(ROOT/packet['resource_bundle']))


if __name__ == '__main__': raise SystemExit(main())
