"""V26 route for the zero-sanity 2026 event ``逐影集趣``.

The local MAA installation can lag behind the official game-resource bundle.
This adapter installs only the pinned ``act1dp`` tile descriptions (with
SHA-256 verification and a reversible backup), declares the real DP stage
graph, and keeps ordinary stamina independent from this zero-sanity event.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.parse
import urllib.request


EVENT_NAME = "逐影集趣"
OFFICIAL_REPOSITORY = "MaaAssistantArknights/MaaAssistantArknights"
OFFICIAL_COMMIT = "bb2c5fbd4ff2731b807908e6da78313a5e60c4b1"
RESOURCE_BASE = (
    "https://raw.githubusercontent.com/"
    f"{OFFICIAL_REPOSITORY}/{OFFICIAL_COMMIT}/resource/Arknights-Tile-Pos/"
)


DP_RESOURCE_SPECS = (
    ("act1dp_01-activities/act1dp/level_act1dp_01", "DP-1", "act1dp_01", "act1dp_01-activities-act1dp-level_act1dp_01.json", "0E6DF5428FB68BDD9FE15F97CC660DF98A155B5E9A062842389E89D46B9FA4A9"),
    ("act1dp_02-activities/act1dp/level_act1dp_02", "DP-2", "act1dp_02", "act1dp_02-activities-act1dp-level_act1dp_02.json", "8D883F88EB274E7AE1D2CA25DBC3683AFAA5659801948D32CBCED1A86D3FB4E4"),
    ("act1dp_03-activities/act1dp/level_act1dp_03", "DP-3", "act1dp_03", "act1dp_03-activities-act1dp-level_act1dp_03.json", "373D2A806057035CEB0D9D6F0FD384FBB20CBFCFE4CE2D7025EDE373D12BF831"),
    ("act1dp_04-activities/act1dp/level_act1dp_04", "DP-4", "act1dp_04", "act1dp_04-activities-act1dp-level_act1dp_04.json", "EC181690D2494CC0EC0818DEB04458D104D68B104D469856C709DBB344FD8D84"),
    ("act1dp_05-activities/act1dp/level_act1dp_05", "DP-5", "act1dp_05", "act1dp_05-activities-act1dp-level_act1dp_05.json", "90A3270A58DA54DDF66151008AC48CA2D9B17CCFD8E19C09573F727C3EE53BC3"),
    ("act1dp_06-activities/act1dp/level_act1dp_06", "DP-6", "act1dp_06", "act1dp_06-activities-act1dp-level_act1dp_06.json", "C5754A3BE4731D0F24C23C60B694244C338AE82A809D0D574DC28A9641B69FC2"),
    ("act1dp_ex01#f#-activities/act1dp/level_act1dp_ex01", "DP-EX-1", "act1dp_ex01#f#", "act1dp_ex01#f#-activities-act1dp-level_act1dp_ex01.json", "1C80C9F2FA0DB7798D08C63E6D15313253260C767E4F632BFAE579182287BBC8"),
    ("act1dp_ex01-activities/act1dp/level_act1dp_ex01", "DP-EX-1", "act1dp_ex01", "act1dp_ex01-activities-act1dp-level_act1dp_ex01.json", "FBD21B3B2489E1EA2B653FE46AD2630824B2FAC7F1762A54F9A6D518B1FC0DB6"),
    ("act1dp_ex02#f#-activities/act1dp/level_act1dp_ex02", "DP-EX-2", "act1dp_ex02#f#", "act1dp_ex02#f#-activities-act1dp-level_act1dp_ex02.json", "3D3EF5C3153C6A3F3E8010EB815565C570E9B79AB6346E7879620865953CB3D3"),
    ("act1dp_ex02-activities/act1dp/level_act1dp_ex02", "DP-EX-2", "act1dp_ex02", "act1dp_ex02-activities-act1dp-level_act1dp_ex02.json", "B6DB65A081D13357F8C7CD96D262060694D0B2292441AFA82DB4C834C9A7646B"),
    ("act1dp_ex03#f#-activities/act1dp/level_act1dp_ex03", "DP-EX-3", "act1dp_ex03#f#", "act1dp_ex03#f#-activities-act1dp-level_act1dp_ex03.json", "84DA1FCE21F039CC912FFED6B556F39A43448F0226F8E67212461C1BF9FAE525"),
    ("act1dp_ex03-activities/act1dp/level_act1dp_ex03", "DP-EX-3", "act1dp_ex03", "act1dp_ex03-activities-act1dp-level_act1dp_ex03.json", "1E1D6B3C42F3E42B3B4EF89C04A49160C4CA8F2AAEB7E0F98D93AE786B209937"),
    ("act1dp_ex04#f#-activities/act1dp/level_act1dp_ex04", "DP-EX-4", "act1dp_ex04#f#", "act1dp_ex04#f#-activities-act1dp-level_act1dp_ex04.json", "E9CEF39517E5EFC0B30E9CB40A5B0F76394D3B093AD6A42EC6E957D3A764CF00"),
    ("act1dp_ex04-activities/act1dp/level_act1dp_ex04", "DP-EX-4", "act1dp_ex04", "act1dp_ex04-activities-act1dp-level_act1dp_ex04.json", "37BC15F430A8E3D8FDCD5EAC5FE7F8B3FCD74BF74EAF4D2D9AAB03CC748FF9E3"),
    ("act1dp_ex05#f#-activities/act1dp/level_act1dp_ex05", "DP-EX-5", "act1dp_ex05#f#", "act1dp_ex05#f#-activities-act1dp-level_act1dp_ex05.json", "B825631CCF90389B54FAD278BBA09CB5C5A6112A13291295E8F23ACBE673A293"),
    ("act1dp_ex05-activities/act1dp/level_act1dp_ex05", "DP-EX-5", "act1dp_ex05", "act1dp_ex05-activities-act1dp-level_act1dp_ex05.json", "21C12C738280156767A904F5322E68A5C427E84546C1C17BA083B0DFA7E35EFB"),
    ("act1dp_ex06#f#-activities/act1dp/level_act1dp_ex06", "DP-EX-6", "act1dp_ex06#f#", "act1dp_ex06#f#-activities-act1dp-level_act1dp_ex06.json", "41209F1D0B69585B62E8D384E8297EFE54222E7CFE040740AFA4BD1AB3E3683E"),
    ("act1dp_ex06-activities/act1dp/level_act1dp_ex06", "DP-EX-6", "act1dp_ex06", "act1dp_ex06-activities-act1dp-level_act1dp_ex06.json", "5FBB872E171D17CB24759D8BB0A488EB0406981F04A585E55BC1A5B370EA91C5"),
    ("act1dp_s01-activities/act1dp/level_act1dp_sub-01", "DS-1", "act1dp_s01", "act1dp_s01-activities-act1dp-level_act1dp_sub-01.json", "071261D88DB7D909132E5B89057D73A3A22C3FE9D41FEA21D517424568EFF13A"),
    ("act1dp_s02-activities/act1dp/level_act1dp_sub-02", "DS-2", "act1dp_s02", "act1dp_s02-activities-act1dp-level_act1dp_sub-02.json", "07B43FE6960C44BECFE145ACD0AA1563755D29B81F8E358157416B6355550C77"),
    ("act1dp_tr01-activities/act1dp/level_act1dp_tr01", "DP-TR-1", "act1dp_tr01", "act1dp_tr01-activities-act1dp-level_act1dp_tr01.json", "BE8254CFC2732AFF8D73E160B518C0427111E4FCFAB4810CFB02D834EF27ECB1"),
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Codex-Arknights-V26"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _resource_dir(maa_root) -> Path:
    return Path(maa_root) / "resource" / "Arknights-Tile-Pos"


def probe_dp_resources(maa_root) -> dict:
    """Read-only validation of the exact DP subset."""

    root = _resource_dir(maa_root)
    overview_path = root / "overview.json"
    result = {
        "status": "missing",
        "official_commit": OFFICIAL_COMMIT,
        "resource_dir": str(root),
        "expected_files": len(DP_RESOURCE_SPECS),
        "valid_files": 0,
        "missing": [],
        "invalid": [],
    }
    try:
        overview = json.loads(overview_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        result["invalid"].append(f"overview:{type(exc).__name__}")
        return result
    for key, code, stage_id, filename, sha256 in DP_RESOURCE_SPECS:
        entry = overview.get(key)
        expected_entry = {"code": code, "stageId": stage_id, "filename": filename}
        if not isinstance(entry, dict) or any(entry.get(k) != v for k, v in expected_entry.items()):
            result["missing"].append(key)
            continue
        path = root / filename
        try:
            data = path.read_bytes()
        except OSError:
            result["missing"].append(filename)
            continue
        if _digest(data) != sha256:
            result["invalid"].append(filename)
            continue
        try:
            payload = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            result["invalid"].append(filename + ":json")
            continue
        if payload.get("stageId") != stage_id or payload.get("code") != code:
            result["invalid"].append(filename + ":identity")
            continue
        result["valid_files"] += 1
    if not result["missing"] and not result["invalid"]:
        result["status"] = "ready"
    return result


def ensure_dp_resources(maa_root, *, fetch=None, now=None) -> dict:
    """Install the pinned DP subset and preserve every replaced local file."""

    before = probe_dp_resources(maa_root)
    if before["status"] == "ready":
        return {**before, "changed": False, "backup": None}
    fetch = fetch or _download
    root = _resource_dir(maa_root)
    overview_path = root / "overview.json"
    if not overview_path.is_file():
        raise RuntimeError(f"MAA overview missing: {overview_path}")
    downloaded = {}
    for _key, code, stage_id, filename, sha256 in DP_RESOURCE_SPECS:
        url = RESOURCE_BASE + urllib.parse.quote(filename, safe="")
        data = fetch(url)
        if _digest(data) != sha256:
            raise RuntimeError(f"Official DP resource hash mismatch: {filename}")
        try:
            payload = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError(f"Official DP resource is not JSON: {filename}") from exc
        if payload.get("stageId") != stage_id or payload.get("code") != code:
            raise RuntimeError(f"Official DP resource identity mismatch: {filename}")
        downloaded[filename] = data

    now = now or datetime.now().astimezone()
    backup = Path(maa_root) / ".codex-resource-backups" / (
        "dp-v26-" + now.strftime("%Y%m%d-%H%M%S")
    )
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(overview_path, backup / "overview.json")
    existing_files = set()
    for _key, _code, _stage_id, filename, _sha256 in DP_RESOURCE_SPECS:
        path = root / filename
        if path.exists():
            existing_files.add(filename)
            shutil.copy2(path, backup / filename)

    overview = json.loads(overview_path.read_text(encoding="utf-8-sig"))
    for key, code, stage_id, filename, _sha256 in DP_RESOURCE_SPECS:
        overview[key] = {"code": code, "stageId": stage_id, "filename": filename}
    try:
        for filename, data in downloaded.items():
            _atomic_bytes(root / filename, data)
        _atomic_bytes(
            overview_path,
            (json.dumps(overview, ensure_ascii=False, indent=4) + "\n").encode("utf-8"),
        )
        after = probe_dp_resources(maa_root)
        if after["status"] != "ready":
            raise RuntimeError(f"DP resource post-write validation failed: {after}")
    except Exception:
        shutil.copy2(backup / "overview.json", overview_path)
        for _key, _code, _stage_id, filename, _sha256 in DP_RESOURCE_SPECS:
            target = root / filename
            saved = backup / filename
            if filename in existing_files:
                shutil.copy2(saved, target)
            elif target.exists():
                target.unlink()
        raise
    return {
        **after,
        "changed": True,
        "backup": str(backup),
        "source": RESOURCE_BASE,
    }


def build_dp_event() -> dict:
    stages = [
        {"display": f"DP-{index}", "internal": f"act1dp_{index:02d}", "modes": ["normal"]}
        for index in range(1, 5)
    ]
    stages.append({"display": "DS-1", "internal": "act1dp_s01", "modes": ["normal"]})
    stages.extend(
        {"display": f"DP-{index}", "internal": f"act1dp_{index:02d}", "modes": ["normal"]}
        for index in range(5, 7)
    )
    for index in range(1, 5):
        stages.append({
            "display": f"DP-EX-{index}",
            "internal": f"act1dp_ex{index:02d}",
            "challenge_internal": f"act1dp_ex{index:02d}#f#",
            "modes": ["normal", "challenge"],
        })
    stages.append({"display": "DS-2", "internal": "act1dp_s02", "modes": ["normal"]})
    for index in range(5, 7):
        stages.append({
            "display": f"DP-EX-{index}",
            "internal": f"act1dp_ex{index:02d}",
            "challenge_internal": f"act1dp_ex{index:02d}#f#",
            "modes": ["normal", "challenge"],
        })
    return {
        "name": EVENT_NAME,
        "start": "2026-09-20T16:00:00",
        "end": "2026-09-30T03:59:00",
        "reward_end": "2026-10-03T03:59:00",
        "kind": "zero_sanity_new",
        "zero_sanity": True,
        "entry_keywords": [EVENT_NAME],
        "combat_keywords": ["轻游", "欢动", "活动关卡"],
        "section_keywords": {"normal": ["轻游"], "ex": ["欢动"], "s": ["欢动"]},
        "task_keywords": ["逐影之礼"],
        "task_claim_enabled": True,
        "stage_prefix": "DP",
        "farm_stage": None,
        "first_clear_modes": ["normal"],
        "tutorial_stages": [
            {"display": "DP-TR-1", "internal": "act1dp_tr01", "modes": ["normal"]}
        ],
        "prerequisite_stages": [
            {"display": "DP-TR-1", "internal": "act1dp_tr01", "modes": ["normal"],
             "before": "DP-1", "kind": "tutorial"}
        ],
        "stages": stages,
        "_discovery_status": "ready_for_visual_navigation",
        "_discovery_reason": "官方act1dp地图资源与在线精确作业已核验；仍须实机图形导航和战后验收",
        "_source": f"official MAA resources@{OFFICIAL_COMMIT} + MaaCopilot exact stage",
    }


def _is_dp_event(event) -> bool:
    return str((event or {}).get("name") or "").replace(" ", "") == EVENT_NAME


def install(runtime):
    if getattr(runtime, "_dp_event_route_v26_installed", False):
        return runtime

    receipt = ensure_dp_resources(runtime._maa_install_root())
    runtime._RUN_SUMMARY["dp_resource_sync"] = deepcopy(receipt)
    event_config = build_dp_event()
    runtime.ACTIVE_EVENTS[:] = [
        item for item in runtime.ACTIVE_EVENTS if not _is_dp_event(item)
    ]
    runtime.ACTIVE_EVENTS.insert(0, deepcopy(event_config))

    original_configured = runtime._configured_event_from_name
    original_event_steps = runtime._run_full_event_steps
    original_section_key = runtime._event_stage_section_key

    # V23's inventory selector treats every active calendar entry as a stamina
    # event.  DP is explicitly zero-sanity, so remove only this event from the
    # copied snapshot; any simultaneous real stamina event still owns stamina.
    import daily_policy_v23 as daily_policy
    original_integrated_plan = daily_policy.choose_integrated_plan

    def choose_integrated_plan(tip, chip_plans, *, now=None):
        adjusted = deepcopy(tip or {})
        adjusted["active_side_stories"] = [
            item for item in adjusted.get("active_side_stories", [])
            if str(item.get("name") or "").replace(" ", "") != EVENT_NAME
        ]
        result = original_integrated_plan(adjusted, chip_plans, now=now)
        if result.get("status") == "selected":
            result["reason"] = f"DP零理智不占用普通理智；{result.get('reason') or ''}"
        return result

    def configured_event_from_name(name):
        compact = str(name or "").replace(" ", "").replace("<", "").replace(">", "")
        if compact and (EVENT_NAME in compact or compact in EVENT_NAME):
            return deepcopy(event_config)
        return original_configured(name)

    def event_stage_section_key(display_name):
        if _is_dp_event(event_config) and str(display_name).upper() == "DS-2":
            return "ex"
        return original_section_key(display_name)

    def event_steps(event):
        if not _is_dp_event(event):
            return original_event_steps(event)
        run = runtime._RUN_SUMMARY.setdefault(
            "event", {"name": EVENT_NAME, "stages": {}, "navigation": {"status": "pending"}}
        )
        run.update({
            "name": EVENT_NAME,
            "kind": "zero_sanity_new",
            "stamina_diversion_forbidden": False,
            "stamina_policy": "DP零理智首通独立完成；普通理智仍由库存平衡路由处理",
        })
        runtime.reload_maa_after_config_switch("V26 act1dp官方地图资源就绪，从主页进入逐影集趣")
        if not runtime.goto_main_menu():
            run.update(status="navigation_failed", detail="DP路由启动前未确认主页")
            return False, True
        runtime.write_status("第2步: 逐影集趣", "零理智逐关首通→逐影之礼→库存平衡理智关")
        first_clear = runtime.mode_event_first_clear(event)
        run["first_clear_result"] = first_clear
        safe_partial = first_clear in (True, "deferred_event_job", "deferred_ex_job")
        if not safe_partial:
            run.update(
                status="zero_sanity_route_stopped",
                detail=f"DP零理智链未在安全结果收口: {first_clear}",
            )
            return False, True

        reward_ok = True
        if runtime._plan_allows("event_task_claim"):
            reward_ok = runtime.claim_event_task_rewards(event) is True
        if not runtime.goto_main_menu():
            run.update(
                status="zero_sanity_complete_home_unverified",
                detail="DP首通后未确认回到主页，不启动理智战斗",
            )
            return False, True

        # DP does not consume sanity.  Its completion therefore cannot own the
        # account's ordinary stamina route.  V23's single-stage fresh-inventory
        # selector remains the only permitted stamina consumer.
        runtime._RUN_SUMMARY.setdefault("remaining_sanity_use", {}).update({
            "status": "running",
            "detail": "DP为零理智活动；开荒后按本轮新鲜库存选择一个普通资源关",
            "source": "dp_zero_sanity_then_inventory_balance_v26",
        })
        resource_ok = runtime.mode_depot_resource_fallback() is True
        run.update(
            status=("completed" if first_clear is True and reward_ok and resource_ok else "partial"),
            reward_claim_ok=reward_ok,
            ordinary_stamina_route_ok=resource_ok,
        )
        return bool(first_clear is True and reward_ok and resource_ok), True

    configured_event_from_name._dp_event_route_v26 = True
    event_stage_section_key._dp_event_route_v26 = True
    event_steps._dp_event_route_v26 = True
    daily_policy.choose_integrated_plan = choose_integrated_plan
    runtime._configured_event_from_name = configured_event_from_name
    runtime._event_stage_section_key = event_stage_section_key
    runtime._run_full_event_steps = event_steps
    runtime._dp_event_route_v26_installed = True
    runtime.log(
        "  [V26] 逐影集趣零理智路由已启用：官方地图资源、DP/DS/EX分层和后续库存理智链"
    )
    return runtime
