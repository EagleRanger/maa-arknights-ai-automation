"""Report the selected gold-room count, not a hard-coded one-room layout."""
from contextlib import contextmanager
from unittest.mock import patch
import daily_base_333_flow_report_v1 as previous
import daily_final_report_sink_v1 as presentation

ORIGINAL_LINES = previous.scope_lines


def scope_lines(report):
    lines = ORIGINAL_LINES(report)
    summary = report.get('run_summary') or {}
    decision = (summary.get('base_333') or {}).get('decision') or {}
    count = decision.get('pure_gold_manufacture_rooms')
    if type(count) is int and 0 <= count <= 3:
        lines = [line for line in lines if not line.startswith('赤金制造：')]
        lines.append(f'赤金制造：{count}间；龙门币贸易{decision.get("lmd_lines", "未确认")}间；'
                     f'搓玉{decision.get("orundum_lines", "未确认")}条。')
    return lines


@contextmanager
def boundary():
    # Install before the legacy report contexts capture their callback objects.
    with patch.object(previous, 'scope_lines', scope_lines), \
         patch.object(presentation, 'scope_lines', scope_lines):
        yield
