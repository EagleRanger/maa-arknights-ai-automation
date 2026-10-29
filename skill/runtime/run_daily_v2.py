"""固定每日入口V2：复用V1全流程，只升级保全派驻奖励领取服务。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import run_daily as base
import sss_reward_pages_v1 as rewards_v1
import sss_reward_pages_v2 as rewards_v2


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v2.py --mode full"


def check_entry(at=None):
    """只读生产门：核对V2入口、完整配方和所有冻结文件指纹。"""
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V2 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V2 route disagree")
    now = at or datetime.now().astimezone()
    if handoff.get("valid_until") and now >= datetime.fromisoformat(handoff["valid_until"]):
        raise ValueError("Explicit handoff expiry reached")
    gate = resolve_production_recipes(
        ROOT / ".project-reasoning" / "COMPONENTS.json",
        handoff["required_recipes"],
    )
    registry = json.loads(
        (ROOT / ".project-reasoning" / "COMPONENTS.json").read_text(encoding="utf-8")
    )
    ids = {component_id for recipe in gate["resolved"] for component_id in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in ids:
            continue
        for artifact in component.get("artifacts", []):
            if artifact["kind"] != "file":
                raise ValueError("Stable V2 snapshot expects whole-file artifacts")
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            if actual != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    actual_entry = hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper()
    if actual_entry != handoff["production_snapshot_sha256"]:
        raise ValueError("Daily V2 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": handoff["entrypoint"],
        "checked_at": now.isoformat(),
        "sss_window": reward_window(now),
        "daily_expired_by_sss": False,
        "sss_reward_service": "v2",
        "game_actions": 0,
    }


def install_reward_service():
    """让冻结V1核心在本进程内使用已验收V2服务，不改写冻结文件。"""
    rewards_v1.service = rewards_v2.service


def main():
    install_reward_service()
    base.check_entry = check_entry
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
