"""Keep verified Copilot deductions distinct from unavailable native Fight totals."""
from contextlib import contextmanager
from unittest.mock import patch
import copilot_visual_usage_v1 as previous

UNKNOWN='本次作战次数/消耗未确认，不把余额净差当作战消耗。'
KNOWN='本轮开荒费用已单独核实；余额净差不直接当作战消耗。'


def normalize(rows,report):
    evidence=(report.get('run_summary') or {}).get('copilot_visual_usage') or []
    verified=any(r.get('verified') is True and type(r.get('gross_cost')) is int and r['gross_cost']>0 for r in evidence)
    return [KNOWN if verified and row==UNKNOWN else row for row in rows]


@contextmanager
def boundary(app):
    import daily_final_report_sink_v1 as presentation
    with previous.boundary(app):
        original=presentation.effect_lines
        with patch.object(presentation,'effect_lines',lambda report:normalize(original(report),report)):
            yield
