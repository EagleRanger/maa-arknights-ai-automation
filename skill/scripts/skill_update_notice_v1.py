"""Read-only stable-release notices. Never download or replace executable code."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
import json
import hashlib
import os
import re

REPOSITORY = "EagleRanger/maa-arknights-ai-automation"
API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_METADATA_BYTES = 65536
CHECK_INTERVAL = timedelta(days=1)
REMIND_INTERVAL = timedelta(days=7)


def private_state_path(skill_root, runtime_root):
    """Keep notification bookkeeping outside a packaged or managed Skill tree."""
    skill_root = Path(skill_root).resolve()
    candidate = Path(runtime_root).resolve() / 'outputs/skill_update_notice.json'
    if not candidate.is_relative_to(skill_root):
        return candidate
    private_root = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / '.cache'))
    identity = hashlib.sha256(str(skill_root).encode('utf-8')).hexdigest()[:16]
    return private_root / 'ArknightsAutomation/update-notices' / (identity + '.json')


def version(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value or ""))
    return tuple(map(int, match.groups())) if match else None


def read_json(path):
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    # This is the caller's private notification cache, never the Skill/code tree.
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def stamp(value):
    try:
        at = datetime.fromisoformat(value)
        return at if at.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def recent(value, now, interval):
    at = stamp(value)
    return at is not None and timedelta(0) <= now - at < interval


def fetch_latest():
    request = Request(API, headers={"Accept": "application/vnd.github+json",
                                    "User-Agent": "arknights-skill-update-notice/1"})
    with urlopen(request, timeout=3) as response:
        if response.geturl() != API:
            raise ValueError("unexpected metadata redirect")
        raw = response.read(MAX_METADATA_BYTES + 1)
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError("release metadata too large")
    return json.loads(raw)


def check(skill_root, state_path, *, now=None, fetch=fetch_latest):
    """Only release metadata is fetched. An unavailable check cannot fail daily."""
    now = now or datetime.now(timezone.utc)
    identity = read_json(Path(skill_root) / "release.json")
    installed = identity.get("version")
    if identity.get("repository") != REPOSITORY or not version(installed):
        return {"status": "not_configured", "notice": ""}
    state_path = Path(state_path).resolve()
    if state_path.is_relative_to(Path(skill_root).resolve()):
        return {"status": "invalid_cache_location", "notice": ""}
    key = f"{REPOSITORY}@{installed}"
    state = read_json(state_path)
    if state.get("installation") != key:
        state = {"installation": key}
    if not recent(state.get("checked_at"), now, CHECK_INTERVAL):
        state.update(checked_at=now.isoformat(), release=None)
        try:
            remote = fetch()
            tag = remote.get("tag_name")
            if remote.get("draft") or remote.get("prerelease") or not version(tag):
                raise ValueError("not a stable release")
            state["release"] = {"version": tag,
                "url": f"https://github.com/{REPOSITORY}/releases/tag/{tag}"}
            state["check_status"] = "checked"
        except Exception as exc:
            # A notice is optional; no report outcome/resource decision changes.
            state["check_status"] = "unavailable"
            state["error_type"] = type(exc).__name__
        try:
            save_state(state_path, state)
        except OSError:
            return {"status": "cache_unavailable", "notice": ""}
    release = state.get("release") or {}
    latest = version(release.get("version"))
    if not latest:
        return {"status": state.get("check_status", "unavailable"), "notice": ""}
    if latest <= version(installed):
        return {"status": "current", "notice": ""}
    if (state.get("notice_version") == release["version"]
            and recent(state.get("notice_queued_at"), now, REMIND_INTERVAL)):
        return {"status": "reminder_deferred", "notice": ""}
    message = (
        f"方舟自动化 Skill 有新版本：{installed} → {release['version']}。\n"
        "如需更新，请在你的 AI 对话中提出；本提示不会下载或覆盖文件。\n"
        "你的 AI 应对照旧版、本地修改和新版，保留个人配置与进度，"
        "说明合并结果及待确认冲突，再验证更新。\n"
        f"更新说明：{release['url']}"
    )
    return {"status": "update_available", "notice": message,
            "installed_version": installed, "latest_version": release["version"],
            "release_url": release["url"], "installation": key}


def queued(state_path, result, *, now=None):
    """Suppress repeated notices after adding one to the existing report payload."""
    state = read_json(state_path)
    if (not result.get("installation")
            or state.get("installation") != result.get("installation")
            or not version(result.get("latest_version"))):
        return
    state.update(notice_version=result["latest_version"],
                 notice_queued_at=(now or datetime.now(timezone.utc)).isoformat())
    try:
        save_state(state_path, state)
    except OSError:
        pass


@contextmanager
def presentation_boundary(runtime, skill_root, state_path, *, checker=check):
    """Append to the existing final popup; do not change reports or outcomes.

    Runtime's original UTF-8 payload writer remains the only popup producer.
    No new window, timer, updater, download, or game action is created.
    """
    original = runtime._atomic_write_json
    expected = (Path(runtime.BASE) / "outputs/summary_popup_payload.json").resolve()
    def write(path, payload):
        result = None
        if (Path(path).resolve() == expected and isinstance(payload, dict)
                and isinstance(payload.get("message"), str)):
            try:
                result = checker(skill_root, state_path)
                if result.get("notice"):
                    payload = deepcopy(payload)
                    payload["message"] += "\n\n—— Skill 更新提示（不影响今日结果）——\n" + result["notice"]
            except Exception:
                result = None
        value = original(path, payload)
        if result and result.get("notice"):
            try:
                queued(state_path, result)
            except Exception:
                # Bookkeeping cannot prevent the original popup from opening.
                pass
        return value
    with patch.object(runtime, "_atomic_write_json", write):
        yield
