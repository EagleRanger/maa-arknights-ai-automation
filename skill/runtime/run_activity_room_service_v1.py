"""One empty room's trust service only. No daily fallback or cleanup."""
import argparse
from datetime import datetime
import json
from pathlib import Path


def service(runtime, position, output):
    from activity_room_invite_prepare_v1 import prepare
    from activity_room_trust_select_v1 import select
    from activity_room_invite_v1 import commit_one
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    receipt = out/'invite_receipt.json'
    if receipt.is_file():
        prior = json.loads(receipt.read_text(encoding='utf-8'))
        if prior.get('confirmation_sent'):
            return dict(prior, replay_suppressed=True)
    def save(name, value):
        (out/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        return value
    observation = save('prepare_receipt.json', prepare(runtime, position))
    if observation['status'] != 'invitation_list_ready': return observation
    selection = save('selection_receipt.json', select(runtime))
    if selection['status'] != 'trust_candidate_selected': return selection
    room = dict(room_id=observation['room_id'], empty_verified=True,
                observed_at=observation['observed_at'], screenshot=observation['empty_evidence'])
    return commit_one(runtime, room, selection['operator'], out, trust_percent=selection['trust_percent'])


def main():
    p = argparse.ArgumentParser(); p.add_argument('--handoff', required=True); args = p.parse_args()
    packet = json.loads(Path(args.handoff).read_text(encoding='utf-8'))
    if not (packet['workflow'] == 'ARK-ACTIVITY-ONE-EMPTY-ROOM-20261011'
            and datetime.fromisoformat(packet['not_before']) <= datetime.now().astimezone() < datetime.fromisoformat(packet['deadline'])):
        raise ValueError('current one-room service packet required')
    import arknights_auto as app
    app.DEVICE = packet['device']; app.SCRIPT_SCREENSHOT_BACKEND = 'adb'
    result = service(app, packet['position'], packet['output'])
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'invited_verified' else 2


if __name__ == '__main__': raise SystemExit(main())
