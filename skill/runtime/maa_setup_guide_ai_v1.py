"""Skip MAA's human-only demo; our account/environment preflight is unchanged."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import json
import re


def prepare(app):
    version = str(app._maa_version_from_deps() or '').lstrip('v')
    # This exact schema is from the shipped 6.21.2/6.21.3 GuideMaxStep and
    # CurrentGuideTutorialVersion, not a guessed future wizard completion.
    if not re.fullmatch(r'6\.21\.[23]', version):
        return dict(status='guide_schema_not_selected', version=version, changed=False)
    path = Path(app.MAA_CONFIG) / 'gui.new.json'
    cfg = json.loads(path.read_text('utf-8-sig'))
    gui = cfg.setdefault('Gui', {})
    if gui.get('GuideStep') == 7 and gui.get('GuideTutorialVersion') == 2:
        return dict(status='guide_already_skipped', version=version, changed=False)
    before = dict(GuideStep=gui.get('GuideStep'), GuideTutorialVersion=gui.get('GuideTutorialVersion'))
    gui.update(GuideStep=7, GuideTutorialVersion=2)
    app._atomic_write_json(str(path), cfg)
    result = dict(status='human_demo_skipped_for_ai', version=version, changed=True,
                  before=before, after=dict(GuideStep=7, GuideTutorialVersion=2),
                  account_environment_preflight_unchanged=True)
    app.log('[MAA设置指引] AI调用不重复人工演示，已按当前已知版本跳过；真实任务页仍须核验')
    return result


@contextmanager
def boundary(app):
    launch = app._launch_maa_for_background_control
    def start(*a, **k):
        app._RUN_SUMMARY['maa_settings_guide'] = prepare(app)
        return launch(*a, **k)
    with patch.object(app, '_launch_maa_for_background_control', start):
        yield
