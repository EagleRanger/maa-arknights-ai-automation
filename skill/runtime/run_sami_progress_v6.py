"""Public V4 continuation without the legacy display-foreground side effect.

ADB screenshots, navigation and readiness proof are unchanged. This wrapper
does not hot-load an existing owner or acquire a second game controller.
"""
from unittest.mock import patch
import run_sami_progress_v4 as previous

WORKFLOW = 'ARK-SAMI-PROGRESS-V6'


def main():
    import arknights_daily_runtime_v12 as app
    def no_foreground():
        state = app._RUN_SUMMARY.setdefault('background_display', {})
        state['foreground_calls_suppressed'] = state.get('foreground_calls_suppressed', 0) + 1
        # The caller still proves real ADB/game readiness. This return value
        # skips only a display convenience, not the actual environment checks.
        return True
    with patch.object(previous, 'WORKFLOW', WORKFLOW), \
         patch.object(app, '_foreground_mumu_display', no_foreground):
        return previous.main()


if __name__ == '__main__':
    raise SystemExit(main())
