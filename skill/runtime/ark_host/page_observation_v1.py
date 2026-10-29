"""Read through a known loading frame without clicking or reusing its path."""
from daily_base_overview_v1 import overview


def base_loading(items):
    middle = ''.join(str(t).upper().replace(' ', '') for t, x, y in items
                     if 600 < x < 1350 and 500 < y < 820)
    return not overview(items) and 'RHODESISLAND' in middle and 'INFRASTRUCTURECOMPLEX' in middle


def base_frame(app, capture, tag, *, max_frames=6):
    frames = []
    for i in range(max_frames):
        path = capture(tag if i == 0 else f'{tag}_ready_{i}')
        items = app.ocr(path)
        waiting = base_loading(items) or not items
        frames.append(dict(screenshot=str(path), loading=waiting))
        if not waiting: break
        if i + 1 < max_frames: app.wait(1)
    app._RUN_SUMMARY.setdefault('page_observation_waits', []).append(dict(
        expected='base', frames=frames, ready=overview(items)))
    return path  # The caller OCRs this actual final path, never the first path.
