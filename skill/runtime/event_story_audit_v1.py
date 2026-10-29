"""Story nodes are separate objectives, including nodes after the last battle."""
import re


def classify_event_nodes(items, prefix):
    result = {'battle': [], 'story': [], 'tutorial': []}
    for text, x, y in items:
        code = re.sub(r'\s+', '', str(text)).upper()
        code = re.sub('[‐‑‒–—―－]', '-', code)
        if not (100 <= x <= 1820 and 180 <= y <= 960):
            continue
        match = re.fullmatch(re.escape(prefix.upper()) + r'-(?:(ST|TR)-)?([1-9]\d*)', code)
        if not match:
            continue
        kind = {'ST': 'story', 'TR': 'tutorial', None: 'battle'}[match[1]]
        if code not in result[kind]:
            result[kind].append(code)
    return result


def story_audit_complete(discovered, records, scan_complete):
    # Battle results and old story-node presence cannot substitute for a story
    # traversal. Unknown scan coverage remains unknown, never "all cleared".
    return bool(scan_complete and all(
        records.get(code, {}).get('status') in {'played_and_returned_verified', 'already_read_verified'}
        and records[code].get('evidence')
        for code in discovered
    ))


def complete_named_story(app, event, name):
    if not re.fullmatch(re.escape(event['stage_prefix']) + r'-ST-[1-9]\d*', name):
        return {'status': 'wrong_target'}
    if not app.goto_event_map(event):
        return {'status': 'map_unverified'}
    path, items, pos = app._locate_event_stage(name, event)
    if not pos:
        return {'status': 'node_unverified', 'evidence': path}
    nodes = classify_event_nodes(items, event['stage_prefix'])
    if name not in nodes['story']:
        return {'status': 'story_identity_unverified', 'evidence': path}
    # No battle badge/cyan-background heuristic: SR story nodes use artwork
    # unlike the mainline hexagons. Require real story entry, skip and return.
    if not app._clear_event_story_node(event, name, pos):
        return {'status': 'story_transition_unverified', 'before': path}
    after = app.shot('story_audit_return_' + name)
    fresh = app.ocr(after)
    if name not in classify_event_nodes(fresh, event['stage_prefix'])['story']:
        return {'status': 'target_return_unverified', 'before': path, 'evidence': after}
    return {'status': 'played_and_returned_verified', 'before': path, 'evidence': after,
            'battle_started': False, 'all_event_stories_complete': False}
