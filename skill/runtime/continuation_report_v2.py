"""Carry a sealed continuation's pending/history through the outer final sink.

Install outside the full production composition, not only around base.main:
the final presentation happens after base.main has returned.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from daily_final_tail_scope_v1 import annotate, preserved_lines


def apply(report, packet, source):
    annotate(report, packet, source)
    if packet['pending']:
        report.update(overall_status='partial', workflow_completed=False)
    return report


@contextmanager
def boundary(root, packet, source):
    import daily_final_report_sink_v2 as sink
    import daily_final_report_sink_v1 as presentation
    import daily_plain_popup_v1 as plain
    original_reconcile, original_effects, original_popup = sink.reconcile_manifest, presentation.effect_lines, plain.summary

    def effects(report):
        return original_effects(report) + preserved_lines(packet, source)

    def popup(report):
        apply(report, packet, source)
        title, text, outcome = original_popup(report)
        extra = '\n'.join(preserved_lines(packet, source))
        if extra not in text:
            text += '\n\n' + extra
        return title, text, outcome

    def reconcile(path, report, run_id):
        result = original_reconcile(path, report, run_id)
        apply(report, packet, source)
        if packet['pending']:
            result.update(business_complete=False, status='partial_or_blocked',
                          report_domain_issues=deepcopy(report['domain_issues']))
        result['final_tail_continuation'] = deepcopy(report['final_tail_continuation'])
        presentation.write_json(Path(path), result)
        report_path = Path(root) / 'outputs' / f"daily_report_{report['date']}.json"
        presentation.write_json(report_path, report)
        temp = report_path.with_suffix('.md.continuation.tmp')
        temp.write_text(presentation.markdown(report), encoding='utf-8')
        temp.replace(report_path.with_suffix('.md'))
        return result

    with patch.object(sink, 'reconcile_manifest', reconcile), \
         patch.object(presentation, 'effect_lines', effects), patch.object(plain, 'summary', popup):
        yield
