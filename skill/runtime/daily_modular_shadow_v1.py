"""Attach the candidate's read-only diagnostics to V95's existing result sink."""
from contextlib import contextmanager
from unittest.mock import patch
from ark_modules.natural_review import review


@contextmanager
def boundary():
    import daily_run_accounting_v1 as accounting
    old = accounting.attach
    def attach(report, manifest, **kwargs):
        result = old(report, manifest, **kwargs)
        try:
            result['modular_review'] = review(result, manifest)
        except Exception as exc:
            result['modular_review'] = {'status': 'diagnostic_unavailable', 'reason': str(exc),
                                       'game_actions': 0, 'production_control_replaced': False}
        return result
    with patch.object(accounting, 'attach', attach):
        yield
