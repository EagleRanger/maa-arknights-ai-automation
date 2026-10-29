"""Daily V48 candidate: close only the observed exclusive mooncake overlay."""

from __future__ import annotations
from portable_paths import resolve_path as _portable_path

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v18 as v18
import run_daily_v19 as v19
import run_daily_v22 as v22
import run_daily_v23 as v23
import run_daily_v24 as v24
import run_daily_v25 as v25
import run_daily_v26 as v26
import run_daily_v27 as v27
import run_daily_v35 as v35
import run_daily_v36 as v36
import run_daily_v37 as v37
import run_daily_v38 as v38
import run_daily_v39 as v39
import run_daily_v40 as v40
import run_daily_v41 as v41
import run_daily_v42 as v42
import run_daily_v44 as v44
import run_daily_v45 as v45
import run_daily_v46 as v46
import run_daily_v47 as v47

ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v48.py --mode full"


def _ensure_runtime():
    probe = v19._runtime_probe()
    if not probe["preferred"] or not probe["symbols_ready"]:
        raise RuntimeError("V48 requires the verified WorkBuddy Python: " + str(probe))
    return probe


def check_entry(at=None):
    """Read-only admission for the complete immutable recipe and new overlay."""
    from production_component_gate import resolve_production_recipes
    from mooncake_choice_overlay_v1 import is_choice_page
    import arknights_daily_runtime_v12 as runtime
    import daily_current_run_fight_reconciliation_v2 as closure
    import dp_deep_card_recovery_v40 as deep
    import dp_ds_result_navigation_v46 as ds
    import dp_progress_evidence_v38 as evidence
    import dp_resource_integrity_v36 as dp
    import dp_result_navigation_v37 as result
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(
            encoding="utf-8"
        )
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V48 entry is not active")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Contract and V48 disagree")
    gate = resolve_production_recipes(
        ROOT / ".project-reasoning" / "COMPONENTS.json", handoff["required_recipes"]
    )
    registry = json.loads(
        (ROOT / ".project-reasoning" / "COMPONENTS.json").read_text(encoding="utf-8")
    )
    ids = {component for recipe in gate["resolved"] for component in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in ids:
            continue
        for artifact in component.get("artifacts", []):
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            if actual != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    actual_entry = hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper()
    if actual_entry != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V48 entry snapshot changed")
    attention = json.loads(
        (ROOT / "outputs" / "event_page_attention" / "43888c9e4d9c7bd87410.json")
        .read_text(encoding="utf-8")
    )
    if not is_choice_page(attention["observations"][0]["ocr"]):
        raise ValueError("Mooncake live OCR fixture no longer matches")
    probe = {
        "date": "2026-09-22", "start_stamina": 194, "final_stamina": 2,
        "chain_status": {"Fight": {"started": False, "completed": False, "ok": False}},
        "verification": {"Fight链": "未执行"},
        "stamina_validation": {
            "start": {"captured_at": "2026-09-22T14:49:19"},
            "final": {"captured_at": "2026-09-22T15:26:34"},
        },
        "run_summary": {"run_evidence_boundary": {"initialized_at": "2026-09-22T14:47:39"}},
        "fight_handoff": {
            "game_day": "2026-09-22", "recorded_at": "2026-09-22T15:16:15",
            "stage": "PR-B-1", "runs": 11, "sanity_cost_each": 18,
            "sanity_consumed": 198, "series_batches": [1] * 11,
        },
    }
    closure.reconcile_report(probe)
    if not probe["chain_status"]["Fight"]["ok"] or probe["sanity"]["consumed"] != 198:
        raise ValueError("V48 current-run Fight reconciliation probe failed")

    old_map = result._is_dp_light_map
    result._is_dp_light_map = lambda items: old_map(items) or deep._is_dp_deep_card_map(items)
    try:
        persistent = {
            stage: evidence._images_reverify_dp_clear(
                runtime, evidence.EVENT_NAME, stage, "normal"
            )
            for stage in ("DP-2", "DP-3", "DP-4", "DP-5")
        }
    finally:
        result._is_dp_light_map = old_map
    if not all(persistent.values()):
        raise ValueError(f"V48 durable DP evidence failed: {persistent}")

    old_fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "ds1_result_ocr_v45.json").read_text(encoding="utf-8")
    )
    challenge_fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "ds1_challenge_result_ocr_v46.json").read_text(encoding="utf-8")
    )
    ds_probes = {
        "finished": ds._ds_result_stage(old_fixture),
        "challenge": ds._ds_result_stage(challenge_fixture),
    }
    if ds_probes != {"finished": "DS-1", "challenge": "DS-1"}:
        raise ValueError(f"V48 DS result fixtures failed: {ds_probes}")
    ds_checkpoint = ds._images_reverify_ds_clear(runtime, "逐影集趣", "DS-1", "normal")
    if not ds_checkpoint:
        raise ValueError("V48 DS-1 immutable result+map checkpoint failed")
    ex_recovery_probe = ds._is_dp_ex_card_map([
        ("LOCKEI", 200, 100), ("DOLLY'S PLAYGROUND", 500, 100),
        ("通关DP-EX-2解锁", 900, 500), ("DP-EX-1", 1200, 650),
    ])
    if not ex_recovery_probe:
        raise ValueError("V48 deep EX card-map recovery probe failed")
    now = at or datetime.now().astimezone()
    return {
        "status": "PASS",
        "entrypoint": handoff["entrypoint"],
        "recipe": handoff["required_recipes"],
        "checked_at": now.isoformat(),
        "sss_window": reward_window(now),
        "runtime": v19._runtime_probe(),
        "dp_resource_probe": dp.probe_dp_resources(
            Path(_portable_path('maa'))
        ),
        "dp_persistent_checkpoints": {"DP-1": "via_DP-2", **persistent},
        "ds_custom_result_probes": ds_probes,
        "ds_persistent_checkpoint": {"DS-1": ds_checkpoint},
        "dp_ex_formation_recovery": "single_visible_ex_plus_brand_and_lock_semantics",
        "ds_edge_navigation": "exact_label_recenter_then_second_ocr",
        "current_run_fight_report": "boundary_after_start+cost_identity+sanity_equation",
        "choice_policy": "close_without_selection; verify_page_changed; never_report_claim",
        "game_actions": 0,
    }


def install_v48_runtime_adapters():
    v47.install_v47_runtime_adapters()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v48_bound", False):
        return

    def install_all():
        runtime = current()
        import mooncake_choice_overlay_v1 as choice
        choice.install(runtime)
        return runtime

    install_all._daily_v48_bound = True
    v18.install_v18_runtime_adapters = install_all


def main():
    _ensure_runtime()
    import run_daily as base

    install_v48_runtime_adapters()
    base.ENGINE_SHA256 = hashlib.sha256(
        (ROOT / "arknights_daily_runtime_v12.py").read_bytes()
    ).hexdigest().upper()
    for module in (
        base, v18, v19, v22, v23, v24, v25, v26, v27, v35, v36,
        v37, v38, v39, v40, v41, v42, v44, v45, v46, v47,
    ):
        module.check_entry = check_entry
    return v19.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    _ensure_runtime()
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())
