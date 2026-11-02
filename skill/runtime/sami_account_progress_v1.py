"""Wire reusable account facts into the actual Sami culture-service decision."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import json

from account_progress_v1 import AccountProgress, account, uid_from_items
from daily_home_state_v1 import home_anchors
from sami_culture_complete_v1 import complete_items

REVISION = 'sami-culture-43-v1'


def observe_account(app):
    frames, identities = [], []
    for _ in range(2):
        path = str(app.shot('roguelike_account_identity'))
        items = app.ocr(path)
        uid = uid_from_items(items)
        if not home_anchors(items) or not uid:
            return None, []
        frames.append(path); identities.append(uid)
        app.wait(.3)
    if identities[0] != identities[1] or frames[0] == frames[1]:
        return None, []
    return account(app.PKG, identities[0]), frames


def home_complete(items):
    return any('研究完成' in ''.join(str(t).split()) and x < 750 and 570 <= y <= 750
               for t, x, y in items)


def record_complete(store, app, result, *, run_id, identity_evidence, revision=REVISION):
    """Import only a UI-verified terminal plus a verified return-home receipt."""
    screenshot = result.get('terminal_screenshot')
    if not (result.get('ok') is True and result.get('terminal_complete') is True
            and result.get('progress') == 43 and result.get('home_confirmed_after') is True
            and screenshot and complete_items(app.ocr(screenshot))):
        return False
    store.remember_complete(theme='Sami', capability='permanent_growth', revision=revision,
        progress=43, total=43, terminal_verified=True, run_id=run_id,
        evidence=[screenshot], identity_evidence=identity_evidence)
    return True


@contextmanager
def boundary(sami, app, *, root, run_id, observer=observe_account):
    root = Path(root)
    old_ensure, old_culture, old_page = app.ensure_env, sami.service_culture, sami.page
    current = dict(identity=None, identity_evidence=[])
    def bind(identity, evidence):
        current.update(identity=identity, identity_evidence=evidence)
        app._RUN_SUMMARY['account_identity'] = dict(verified=identity is not None,
            account=identity, evidence=[str(p) for p in evidence])
    def ensure(*a, **kw):
        result = old_ensure(*a, **kw)
        if result is True:
            identity, evidence = observer(app)
            bind(identity, evidence)
        return result
    def page(*a, **kw):
        value = old_page(*a, **kw)
        # ensure_env can finish on START rather than the ordinary home. Bind
        # at the actual normal-home navigation seam before it leaves that UI.
        if home_anchors(value[1]) and uid_from_items(value[1]):
            bind(*observer(app))
        return value
    def culture(*a, **kw):
        identity = current['identity']
        # Missing account identity disables the skip, not the independent game.
        store = AccountProgress(root/'runtime_state/accounts', identity) if identity else None
        policy_path = root/'config/roguelike_tree_revisions.json'
        try:
            policy = json.loads(policy_path.read_text(encoding='utf-8')) if policy_path.exists() else {}
        except (OSError, ValueError):
            policy = {}; store = None
        revision = policy.get('Sami', REVISION)
        if not isinstance(revision, str) or not revision.strip():
            revision = REVISION; store = None
        decision = store.decision(theme='Sami', capability='permanent_growth', revision=revision) if store else dict(
            action='inspect', reason='current_account_unverified')
        app._RUN_SUMMARY.setdefault('account_progress_decisions', []).append(decision)
        if decision['action'] == 'skip_permanent_complete':
            # A cheap current HOME observation detects contradiction without
            # opening the tree. Changed theme/revision/account never hits cache.
            path, items, text = sami.page('sami_complete_cache_home_guard')
            if sami.is_sami_home(text) and home_complete(items):
                return dict(ok=True, reason='account_culture_complete_cached', progress=decision['fact']['progress'],
                    terminal_complete=True, cache_hit=True, skipped_tree=True,
                    account_fact=str(store.path), home_confirmed_after=True,
                    screenshots=[str(path)], upgrades=[], source_run_id=decision['fact']['source_run_id'])
            # Missing OCR text alone is NOT evidence that a permanent upgrade
            # disappeared. Fall back to the original inspector this time;
            # replace/invalidate only on positive new evidence or revision.
        result = old_culture(*a, **kw)
        if store:
            try:
                if record_complete(store, app, result, run_id=run_id,
                                   identity_evidence=current['identity_evidence'], revision=revision):
                    result = dict(result, account_fact=str(store.path), account_completion_recorded=True)
                elif result.get('ok') is True and type(result.get('progress')) is int and 0 <= result['progress'] < 43:
                    # An explicit smaller measured counter contradicts the cache.
                    store.invalidate(theme='Sami', capability='permanent_growth', revision=revision,
                                     reason='current_tree_explicit_partial_counter')
            except (OSError, ValueError, KeyError, TypeError) as exc:
                # A private fact-file maintenance error does not erase a real
                # successful game effect or turn it into a battle failure.
                result = dict(result, account_fact_error=f'{type(exc).__name__}: {exc}')
        return result
    with patch.object(app, 'ensure_env', ensure), patch.object(sami, 'page', page), \
            patch.object(sami, 'service_culture', culture):
        yield current
