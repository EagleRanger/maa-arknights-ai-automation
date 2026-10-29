"""Keep run-start evidence immutable while still returning fresh segment reads.

No balance is inferred and no capture is skipped. This adapter changes only
the observation key, not the OCR, resource policy or business outcome.
"""
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from unittest.mock import patch


def valid(record):
    return (isinstance(record, dict) and record.get('verified') is True
            and type(record.get('value')) is int and record['value'] >= 0)


def install(app):
    original = app._capture_stamina_observation
    if getattr(original, '_stamina_scope_v1', False):
        return app

    @wraps(original)
    def capture(phase, *args, **kwargs):
        observations = app._RUN_SUMMARY.setdefault('stamina_observations', {})
        first = deepcopy(observations.get('start'))
        if str(phase) != 'start' or not valid(first):
            return original(phase, *args, **kwargs)
        index = 1
        while f'segment_start_{index}' in observations:
            index += 1
        label = f'segment_start_{index}'
        try:
            result = original(label, *args, **kwargs)
            if isinstance(result, dict):
                # A wrapper may return a different object from the stored one.
                observations[label] = dict(deepcopy(result), phase=label,
                    observation_scope='segment_start', requested_phase='start')
            return result  # The caller still sees the fresh current balance.
        finally:
            # Also defend against a legacy capture that ignores its label.
            observations['start'] = first

    capture._stamina_scope_v1 = True
    app._capture_stamina_observation = capture
    return app


@contextmanager
def boundary(app):
    """Install at the existing final engine seam, after legacy OCR adapters."""
    import daily_environment_final_boundary_v1 as final
    original = final.install
    saved = []
    def install_after_environment(runtime):
        result = original(runtime)
        saved.append((runtime, runtime._capture_stamina_observation))
        return install(result)
    try:
        with patch.object(final, 'install', install_after_environment):
            yield
    finally:
        for runtime, capture in reversed(saved):
            runtime._capture_stamina_observation = capture
