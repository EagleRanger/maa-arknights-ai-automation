"""Candidate 333 supply planner; reuse the frozen MAA action/receipt path.

No imports install this policy. An explicit outer boundary is required. Missing
rate evidence falls back to more supply, not a block on the rest of daily work.
Neither a projection nor a written plan constitutes actual six-room acceptance.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from math import floor
from unittest.mock import patch

from ark_modules.base_forecast import fit_rates, number
import daily_base_333_flow_balance_v1 as previous
import daily_base_333_verified_execution_v1 as base
from base_333_inventory_forecast_v1 import stamp

VERSION = "v2_cycle_supply"
MAX_CYCLE_HOURS = 24


def now():
    return datetime.now().astimezone()


def _age(value, at, seconds):
    try:
        return 0 <= (at - stamp(value)).total_seconds() <= seconds
    except (TypeError, ValueError):
        return False


def decorate_decision(decision, *, at=None):
    """Preserve jade/stamina eligibility; replace only the gold factory count."""
    result = deepcopy(decision)
    if result.get("status") != "selected":
        return result
    at = at or now()
    lines = result.get("orundum_lines")
    if (type(lines) is not int or lines not in (0, 1, 2)
            or any(type(result.get(k)) is not int or result[k] < 0
                   for k in ("pure_gold", "rock", "lmd"))
            or not _age(result.get("sync_time"), at, 3600)):
        result.update(status="inventory_unverified", plan_index=None,
                      reason="current_nonnegative_inventory_required")
        return result
    # Keep the accepted surplus ceiling. Below it, unknown throughput must not
    # silently assign one supplier to three consumers as V1 did.
    gold = 0 if result["pure_gold"] >= previous.GOLD_PAUSE_AT else 3 - lines
    result.update(source=VERSION, gold_production_paused=gold == 0,
                  pure_gold_manufacture_rooms=gold,
                  record_manufacture_rooms=3 - lines - gold,
                  rate_balance_verified=False,
                  cycle_balance={"basis": "stock_recovery_fallback",
                                 "horizon_hours": MAX_CYCLE_HOURS,
                                 "forecast_available": False,
                                 "reason": "no_matched_cycle_observation",
                                 "free_input_shard_jobs": min(result["rock"] // 2, result["lmd"] // 1600),
                                 "reserved_shard_jobs": None,
                                 "jade_cycle_sustainability": "unverified" if lines else "not_applicable",
                                 "actual_balance_verified": False})
    result["reason"] += ("；赤金达到既定积压门槛，暂缓增产"
                         if gold == 0 else f"；缺少可靠周期余量，非搓玉的{gold}间制造站优先补赤金")
    return result


def _layout(payload, lines, gold):
    """Do not touch trade settings, operators, dorms, power or supply drones."""
    result = deepcopy(payload)
    products = base.expected_products(result)
    if (type(lines) is not int or lines not in (0, 1, 2)
            or type(gold) is not int or not 0 <= gold <= 3 - lines
            or sum(p == "Orundum" for (f, _), p in products.items() if f == "Trade") != lines
            or sum(p == "Originium Shard" for (f, _), p in products.items() if f == "Mfg") != lines):
        raise ValueError("paired 333 layout required")
    rooms = result["plans"][0]["rooms"]["manufacture"]
    adjustable = [r for r in rooms if r["product"] != "Originium Shard"]
    # Keep an existing gold room before converting additional record rooms.
    adjustable.sort(key=lambda r: r["product"] != "Pure Gold")
    for index, room in enumerate(adjustable):
        room["product"] = "Pure Gold" if index < gold else "Battle Record"
    return result


def profile_id(payload):
    """Bind historical flow measurements to products AND the entire roster."""
    rooms = payload["plans"][0]["rooms"]
    return hashlib.sha256(json.dumps(rooms, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def _fixed_roster(payload):
    # Autofill may choose a different combo each visit. Configuration equality
    # alone therefore cannot establish equal throughput under autofill.
    rooms = payload["plans"][0]["rooms"]
    return all(r.get("autofill") is False and r.get("operators")
               and r.get("skip") is False
               for group in rooms.values() for r in group)


def gold_budget(payload, decision, observation, *, at, hours):
    """Project one matched roster; gold quantities, never generic order counts.

    Samples contain settled gold_produced/gold_demand per room-hour, including
    special-order actual gold quantities. Current free capacities and pending
    order costs must be independently observed. Uncollected output is excluded.
    """
    unknown = {"status": "unknown", "actual_balance_verified": False}
    if not _fixed_roster(payload):
        return dict(unknown, reason="autofill_roster_not_rate_stable")
    identity = profile_id(payload)
    if not isinstance(observation, dict):
        return dict(unknown, reason="no_cycle_observation")
    row = observation.get(identity) or {}
    if not isinstance(row, dict):
        return dict(unknown, reason="invalid_cycle_observation")
    if (row.get("profile") != identity or not row.get("evidence")
            or row.get("verified") is not True
            or row.get("inventory_sync_time") != decision.get("sync_time")
            or not _age(row.get("observed_at"), at, 3600)
            or row.get("collection_interval_hours") != hours):
        return dict(unknown, reason="matched_current_cycle_observation_required")
    fields = ("gold_free_capacity", "new_order_gold_capacity", "pending_gold_demand")
    if any(type(row.get(k)) is not int or row[k] < 0 for k in fields):
        return dict(unknown, reason="capacity_or_pending_order_unknown")
    supplied = row.get("samples")
    if not isinstance(supplied, list):
        return dict(unknown, reason="rate_samples_missing")
    samples = [s for s in supplied if isinstance(s, dict) and s.get("collection_interval_hours") == hours]
    # Two labels for an overlapping observation are not two independent cycles.
    windows = {}
    independent = []
    for sample in samples:
        try:
            start, end = stamp(sample["start"]), stamp(sample["end"])
            flow = sample["flow"]
            if any(start < b and end > a for a, b in windows.get(flow, [])):
                continue
            if start >= end:
                continue
            windows.setdefault(flow, []).append((start, end))
            independent.append(sample)
        except (KeyError, TypeError, ValueError):
            continue
    fit = fit_rates(independent, at, profile=identity)
    products = base.expected_products(payload)
    gold = sum(p == "Pure Gold" for (f, _), p in products.items() if f == "Mfg")
    trades = sum(p == "LMD" for (f, _), p in products.items() if f == "Trade")
    output = fit["rates"].get("gold_produced", {})
    demand = fit["rates"].get("gold_demand", {})
    if not demand.get("sufficient") or (gold and not output.get("sufficient")):
        return dict(unknown, reason="two_reconciled_rate_samples_required", fit=fit)
    produced = min(floor(output.get("low", 0) * gold * hours), row["gold_free_capacity"])
    needed = min(demand["high"] * trades * hours, row["new_order_gold_capacity"])
    available = decision["pure_gold"] - row["pending_gold_demand"]
    # One stock buffer is deliberately explicit. It is a planning margin, not
    # an asserted operator skill, market reward or current order price.
    reserve = 20
    end = available + produced - needed
    return {"status": "projected_sufficient" if end >= reserve else "projected_shortage",
            "profile": identity, "horizon_hours": hours,
            "gold_produced_lower": produced, "gold_demand_upper": needed,
            "pending_gold_demand": row["pending_gold_demand"], "gold_reserve": reserve,
            "end_gold_lower": end, "shortfall": max(0, reserve - end),
            "pending_shortfall_now": max(0, -available),
            "actual_balance_verified": False, "evidence": row["evidence"],
            "note": "按已测同阵容周期估计；待收货未当现有库存，特殊订单按真实赤金数量采样。"}


def balance_payload(payload, decision, *, observation=None, at=None, hours=24):
    if not number(hours) or not 0 < hours <= MAX_CYCLE_HOURS:
        raise ValueError("cycle must be within 24 hours")
    if decision.get("status") != "selected" or decision.get("source") != VERSION:
        raise ValueError("fresh V2 inventory decision required")
    at = at or now()
    if not _age(decision.get("sync_time"), at, 3600):
        raise ValueError("inventory decision expired before configuration")
    lines = decision["orundum_lines"]
    options = []
    for gold in range(4 - lines):
        candidate = _layout(payload, lines, gold)
        budget = gold_budget(candidate, decision, observation, at=at, hours=hours)
        options.append(dict(gold_rooms=gold, budget=budget))
    feasible = [o for o in options if o["budget"]["status"] == "projected_sufficient"]
    selected = min(feasible, key=lambda o: o["gold_rooms"]) if feasible else None
    gold = selected["gold_rooms"] if selected else decision["pure_gold_manufacture_rooms"]
    # Contrary fresh measured evidence can override the static surplus ceiling.
    # If all layouts are measured and short, maximize available supply, not EXP.
    fallback_budget = options[gold]["budget"]
    measured_shortage = not selected and fallback_budget["status"] == "projected_shortage"
    if measured_shortage:
        gold = 3 - lines
    cycle = dict(decision["cycle_balance"], horizon_hours=hours, options=options,
                 forecast_available=selected is not None,
                 basis="measured_cycle_projection" if selected else "stock_recovery_fallback")
    if selected:
        cycle.update(reason="minimum_gold_rooms_cover_cycle", selected_budget=selected["budget"])
    elif measured_shortage:
        cycle.update(reason="measured_shortage_supply_recovery")
        if options[-1]["budget"]["status"] != "unknown":
            cycle.update(forecast_available=True, selected_budget=options[-1]["budget"])
    result = _layout(payload, lines, gold)
    decision.update(pure_gold_manufacture_rooms=gold, record_manufacture_rooms=3-lines-gold,
                    gold_production_paused=gold == 0, cycle_balance=cycle)
    decision["reason"] = (f"实时仓库固源岩{decision['rock']}、龙门币{decision['lmd']}、赤金{decision['pure_gold']}；"
                          f"保留{lines}条搓玉线；按周期预算/库存补给选择{gold}金、{3-lines-gold}经验制造；"
                          f"理智路线不变：{decision['stamina_target']}")
    result["plans"][0]["drones"] = previous.manufacture_target(result)
    # Honour an outer/supplied reservation too; never revive disabled drones.
    if payload["plans"][0].get("drones", {}).get("enable") is False:
        result["plans"][0]["drones"]["enable"] = False
    result["plans"][0]["description"] = (
        f"{lines}合成玉+{3-lines}龙门币贸易；{lines}碎片+{gold}赤金+{3-lines-gold}作战记录制造")
    result["flow_balance"] = dict(policy=VERSION, jade_trade_rooms=lines,
        shard_manufacture_rooms=lines, gold_manufacture_rooms=gold,
        gold_production_paused=gold == 0, gold_inventory=decision["pure_gold"],
        inventory_sync_time=decision["sync_time"], rate_balance_verified=False,
        cycle=deepcopy(cycle))
    return result


def report_lines(report):
    base_summary = (report.get("run_summary") or {}).get("base_333") or {}
    decision = base_summary.get("decision") or {}
    if decision.get("source") != VERSION:
        return []
    receipt = base_summary.get("execution_receipt") or {}
    complete = all(receipt.get(k) is True for k in
                   ("config_loaded", "products_verified", "operator_rotation_verified", "task_chain_completed"))
    lines = decision["orundum_lines"]
    gold = decision["pure_gold_manufacture_rooms"]
    prefix = "基建已核验" if complete else "基建计划（实际换产待核验）"
    result = [f"{prefix}：制造{lines}碎片/{gold}赤金/{3-lines-gold}经验；贸易{lines}玉/{3-lines}币。"]
    cycle = decision.get("cycle_balance") or {}
    budget = cycle.get("selected_budget") or {}
    if budget:
        result.append(f"下次收货前预估：赤金产出至少{budget['gold_produced_lower']:.0f}、"
                      f"新订单消耗至多{budget['gold_demand_upper']:.0f}，"
                      f"另有旧单需要{budget['pending_gold_demand']}；这是预测，不是到账。")
        if budget["shortfall"]:
            result.append(f"赤金预估仍缺{budget['shortfall']:.0f}，已优先补产；不能保证贸易不停工。")
    else:
        result.append("产销速度尚未实测：按库存保守补给，不宣称能持续满产。")
    if lines:
        result.append(f"当前空闲原料最多可新排产{cycle.get('free_input_shard_jobs', '未知')}份碎片"
                      "（不含已预扣队列）；全天持续供料仍待核验。")
    return result


@contextmanager
def boundary(*, observation=None, at=None, hours=24):
    """Compose OUTSIDE the existing full graph and its drone reservation.

    The owner still holds game exclusivity and installs the accepted action and
    receipt components. This context never starts/cleans up an application.
    """
    import daily_base_333_flow_report_v1 as flow_report
    import daily_plain_popup_v3 as popup
    old_scope, old_summary = flow_report.scope_lines, popup.summary

    def scope(report):
        extra = report_lines(report)
        current = old_scope(report)
        return ([s for s in current if not s.startswith("赤金制造：")] + extra) if extra else current

    def summary(report):
        title, text, status = old_summary(report)
        return title, "\n".join([text, *report_lines(report)]), status

    with patch.object(previous, "decorate_decision", lambda d: decorate_decision(d, at=at)), \
         patch.object(previous, "balance_payload", lambda p, d: balance_payload(
             p, d, observation=observation, at=at, hours=hours)), \
         patch.object(flow_report, "scope_lines", scope), patch.object(popup, "summary", summary):
        yield
