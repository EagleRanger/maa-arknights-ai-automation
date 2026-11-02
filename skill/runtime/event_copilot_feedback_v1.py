"""Small event failure notice and rejection of explicitly unavailable jobs.

No battle control, author/video conversion, retry reset or resource change.
"""
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path
import re


def unavailable_reason(data):
    doc = data.get('doc') or {}
    text = re.sub(r'\s+', '', str(doc.get('title', '')) + '\n' + str(doc.get('details', '')))
    # Only explicit, current incompatibility declarations. A request to update
    # resources or a historical fixed bug alone does not mean unusable.
    markers = ('暂时用不了', '现在无法部署干员', '正在修', '等maa修复', '等待maa修复')
    if any(term in text.lower() for term in markers) and any(
        term in text.lower() for term in ('地图', '坐标', '部署', '定位')
    ):
        return '作者说明当前地图/部署不兼容，暂不可用'
    return ''


def stage_lines(report):
    event = (report.get('run_summary') or {}).get('event') or {}
    lines = []
    # Only stages present in this run; do not list the historical checkpoint.
    for stage, row in (event.get('stages') or {}).items():
        modes = row.get('modes') or {'normal': row}
        for mode, state in modes.items():
            status = state.get('status')
            if status not in {'failed', 'imperfect', 'technical_error', 'navigation_unverified',
                              'no_job', 'job_incompatible', 'needs_ai_tutorial', 'manual_required'}:
                continue
            name = str(stage) + ('突袭' if mode == 'challenge' else '')
            # Budget use may include leaked/stalled/unknown attempts. Only
            # explicitly verified defeats can be called "N failures".
            jobs = list(dict.fromkeys(x for x in state.get('attempted_jobs', []) if x))
            verified = set(state.get('verified_failed_jobs') or [])
            detail = str(state.get('detail') or '')
            failed = status == 'failed' and ('战斗结果=failed' in detail or '结算=failed' in detail)
            suffix = f'，{len(jobs)}次失败' if failed and jobs and set(jobs) <= verified else ''
            lines.append(f'{name} 未完成{suffix}。')
    return list(dict.fromkeys(lines))


@contextmanager
def boundary(app):
    import daily_plain_popup_v3 as popup
    old_summary, old_effects = popup.summary, popup.effect_lines
    old_compat = app._copilot_auto_compatibility
    old_update = getattr(app, '_update_event_progress', None)

    def update(event_name, stage, status, detail='', mode=None, **kwargs):
        # Add evidence to the existing account progress, without changing the
        # retry counter or resurrecting any stage. The original final writer
        # also feeds the actual current-run summary after this enrichment.
        previous = (((app._load_event_progress().get('events') or {}).get(event_name) or {})
                    .get('stages') or {}).get(stage) or {}
        failed_jobs = list(((previous.get('modes') or {}).get(mode) or {}).get('verified_failed_jobs') or [])
        if kwargs.get('reset_attempted_jobs'):
            failed_jobs = []
        discard = Path(str(kwargs.get('discard_attempt') or '')).name
        failed_jobs = [name for name in failed_jobs if name != discard]
        if kwargs.get('record_attempt', True) and re.search(r'(?:战斗结果|结算|本次强制重打结果)=failed(?:;|；|\s|$)', detail):
            failed_jobs.extend(re.findall(r'[A-Za-z0-9_-]+\.json', detail))
        writer = app._atomic_write_json
        def write(path, value):
            if mode and Path(path).resolve() == Path(app.EVENT_PROGRESS_FILE).resolve():
                row = value['events'][event_name]['stages'][stage]['modes'][mode]
                row['verified_failed_jobs'] = list(dict.fromkeys(failed_jobs))
            return writer(path, value)
        with patch.object(app, '_atomic_write_json', write):
            return old_update(event_name, stage, status, detail, mode=mode, **kwargs)

    def summary(report):
        title, text, status = old_summary(report)
        additions = stage_lines(report)
        if additions:
            lines = text.splitlines()
            at = next((i for i, line in enumerate(lines) if line.startswith('待处理：')), len(lines)-1)
            lines[at:at] = additions
            text = '\n'.join(lines)
        return title, text, status

    def effects(report):
        return old_effects(report) + stage_lines(report)

    def compatibility(data):
        ok, reason = old_compat(data)
        extra = unavailable_reason(data)
        return (False, '；'.join(x for x in (reason, extra) if x)) if extra else (ok, reason)

    from contextlib import ExitStack
    with ExitStack() as stack:
        stack.enter_context(patch.object(popup, 'summary', summary))
        stack.enter_context(patch.object(popup, 'effect_lines', effects))
        stack.enter_context(patch.object(app, '_copilot_auto_compatibility', compatibility))
        if old_update:
            stack.enter_context(patch.object(app, '_update_event_progress', update))
        yield
