"""Exact, date-bound museum classification; retain all unknown-event guards."""
from copy import deepcopy
from pathlib import Path
import json
import zero_sanity_event_policy_v1 as v1
import zero_sanity_event_policy_v2 as previous

EVIDENCE = Path(__file__).resolve().parent / 'config/museum_evolution_20261024_evidence.json'


def museum_record(data=None):
    data = data if data is not None else json.loads(EVIDENCE.read_text(encoding='utf-8'))
    expected = {f'act1museum_m{zone}_{stage:02d}' for zone in range(1, 5) for stage in range(1, 4)}
    stages = data['stages']
    if (data['event_id'] != 'act1museum' or data['name'] != '视相博物馆：演化'
            or data['type'] != 'ARCADE' or len(stages) != 12
            or {s['stageId'] for s in stages} != expected
            or any(type(s['apCost']) is not int or s['apCost'] != 0
                   or s['canBattleReplay'] is not False for s in stages)):
        raise ValueError('museum stage identity/cost evidence mismatch')
    return dict(id='act1museum-20261024', name=data['name'],
        starts_at=data['starts_at'], expires_at=data['expires_at'],
        consumes_sanity=False, progression='separate_non_stamina_pending',
        maa_route='no_current_unique_full_event_route', classifier_version='v3',
        evidence=[str(EVIDENCE), data['announcement'], data['source_root'] + 'stage_table.json'],
        match_kind='exact_name_and_pinned_stage_costs')


def classify_zero_sanity_event(name, *, at=None):
    record = museum_record()
    if v1._normalize(name) == v1._normalize(record['name']) and v1._active(record, at):
        return record
    return previous.classify_zero_sanity_event(name, at=at)


def install(runtime):
    if getattr(runtime, '_zero_sanity_event_policy_v3_installed', False):
        return runtime
    original_classify = runtime._non_stamina_activity_from_name
    original_detect = runtime.detect_terminal_limited_event

    def classify(name):
        return classify_zero_sanity_event(name) or original_classify(name)

    def detect():
        result = original_detect()
        special = classify_zero_sanity_event(result.get('name')) if isinstance(result, dict) and result.get('status') == 'open' else None
        if special:
            result.update(classification='zero_sanity_special_event', canonical_name=special['name'],
                ignored_for_stamina_routing=True, consumes_sanity=False,
                progression_status=special['progression'], policy_id=special['id'])
            runtime._RUN_SUMMARY['zero_sanity_event'] = dict(deepcopy(special),
                status='recognized_nonblocking', observed_name=result['name'],
                stamina_routing='continue_existing_no_stamina_event_policy')
        return result

    runtime._non_stamina_activity_from_name = classify
    runtime.detect_terminal_limited_event = detect
    runtime._zero_sanity_event_policy_v3_installed = True
    return runtime
