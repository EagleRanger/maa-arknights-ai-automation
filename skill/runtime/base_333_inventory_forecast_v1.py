"""Offline candidate: forecast 333 inventories, never control the game.

Only reconciled same-plan observations may train a rate. This candidate does
not replace the frozen chooser or relax its stock/resource boundaries.
"""
from datetime import datetime
from math import isfinite, floor
import re
from statistics import median

import daily_base_333_flow_balance_v1 as baseline

STOCKS = ("rock", "lmd", "gold", "shard")
IDS = {"rock": "30012", "lmd": "4001", "gold": "3003"}

# Recipe reference, NOT a measured roster rate. These are nominal times;
# callers must supply actual effective speed and room buffers for live use.
RECIPE_SOURCES = [
    "https://prts.wiki/w/罗德岛基建/制造站",
    "https://m.prts.wiki/w/罗德岛基建/贸易站",
]
GOLD_HOURS = 1.2
SHARD_HOURS = 1.0
JADE_ORDER_HOURS = 2.0
# Ordinary level-3 orders only. Skills changing orders invalidate this profile.
GOLD_PER_ORDER = 2 * .3 + 3 * .5 + 4 * .2
GOLD_ORDER_HOURS = (144 * .3 + 210 * .5 + 276 * .2) / 60


def verify_room_observations(observations, *, at):
    """Validate explicit current-product observations, not screenshot names.

    Vision/OCR supplies a header and independently read current setting. Counts
    of pending orders and ProductChanged callbacks are insufficient on their own.
    """
    now = stamp(at)
    rooms, errors = {}, []
    for row in observations:
        header = re.sub(r"\s+", "", row.get("header", ""))
        found = re.search(r"(贸易站|制造站)(B\d{3})(?!\d)", header)
        if not found:
            errors.append("room_header_unverified")
            continue
        facility, room = found.groups()
        if room in rooms:
            errors.append("duplicate_room:" + room)
            continue
        product, proof = row.get("current_product"), row.get("proof")
        accepted = ({"LMD", "Orundum"} if facility == "贸易站"
                    else {"Pure Gold", "Battle Record", "Originium Shard"})
        required = "current_order_setting" if facility == "贸易站" else "manufacturing_product_detail"
        try:
            age = (now - stamp(row["observed_at"])).total_seconds()
        except (KeyError, ValueError, TypeError):
            age = -1
        if (product not in accepted or proof != required or not row.get("screenshot")
                or not 0 <= age <= 3600):
            errors.append("current_product_unverified:" + room)
            continue
        rooms[room] = {"facility": facility, "current_product": product,
                       "screenshot": row["screenshot"], "observed_at": row["observed_at"]}
    counts = {f: sum(r["facility"] == f for r in rooms.values()) for f in ("贸易站", "制造站")}
    complete = len(rooms) == 6 and all(n == 3 for n in counts.values()) and not errors
    return {"status": "six_rooms_observed" if complete else "partial",
            "rooms": rooms, "counts": counts, "errors": errors,
            "hourly_balance_verified": False,
            "products_paired": complete and
                sum(r["current_product"] == "Orundum" for r in rooms.values()) ==
                sum(r["current_product"] == "Originium Shard" for r in rooms.values())}


def number(value):
    return type(value) in (int, float) and isfinite(value)


def stamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("observation timestamp needs timezone")
    return result


def fit(samples):
    """Fit net units/hour; external_net includes farm/rewards/manual use.

    Each sample must explicitly account for every stock (zero is explicit),
    stable room products/operators and all non-base flows. Unknown is not zero.
    Two non-overlapping >=1-hour windows per mode are required. Negative worst
    observed rates are retained for conservative stock-depletion forecasts.
    """
    grouped, rejected = {}, []
    for index, sample in enumerate(samples):
        try:
            if sample.get("reconciled") is not True or sample.get("stable_plan") is not True:
                raise ValueError("unreconciled_or_changed_plan")
            start, end = stamp(sample["start"]), stamp(sample["end"])
            hours = (end - start).total_seconds() / 3600
            if hours < 1:
                raise ValueError("window_shorter_than_one_hour")
            mode = sample["mode"]
            if not isinstance(mode, str) or not mode:
                raise ValueError("mode_missing")
            row = {}
            for stock in STOCKS:
                before = sample["before"][stock]
                after = sample["after"][stock]
                external = sample["external_net"][stock]
                if not all(number(x) for x in (before, after, external)) or min(before, after) < 0:
                    raise ValueError("invalid_or_unknown_stock")
                row[stock] = (after - before - external) / hours
            windows = grouped.setdefault(mode, [])
            if any(start < old[1] and end > old[0] for old in windows):
                raise ValueError("overlapping_sample")
            windows.append((start, end, row))
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append({"sample": index, "reason": str(exc)})
    modes = {}
    for mode, windows in grouped.items():
        if len(windows) < 2:
            continue
        modes[mode] = {
            "samples": len(windows),
            "median_net_per_hour": {s: median(w[2][s] for w in windows) for s in STOCKS},
            "conservative_net_per_hour": {s: min(w[2][s] for w in windows) for s in STOCKS},
            "observed_until": max(w[1] for w in windows).isoformat(),
        }
    return {"status": "fitted" if modes else "insufficient_reconciled_samples",
            "modes": modes, "rejected": rejected, "production_enabled": False}


def forecast(stocks, model, hours, reserves=None):
    if not number(hours) or not 0 < hours <= 24:
        raise ValueError("forecast horizon must be within 24 hours")
    reserves = reserves or {}
    rates = model["conservative_net_per_hour"]
    end, runway, violations = {}, {}, []
    for stock in STOCKS:
        value, rate, reserve = stocks.get(stock), rates.get(stock), reserves.get(stock, 0)
        if not all(number(x) for x in (value, rate, reserve)) or min(value, reserve) < 0:
            return {"status": "unknown", "reason": "stock_or_rate_missing:" + stock}
        end[stock] = value + rate * hours
        runway[stock] = max(0, (value - reserve) / -rate) if rate < 0 else None
        if min(value, end[stock]) < reserve:
            violations.append(stock)
    return {"status": "projected_feasible" if not violations else "projected_shortage",
            "end": end, "runway_hours": runway, "violations": violations,
            "horizon_hours": hours, "actual_balance_verified": False}


def recommend(tip, shard, fitted, *, at, horizon_hours):
    """Suggest a plan inside the existing stock policy; no runtime installation."""
    if not number(horizon_hours) or not 0 < horizon_hours <= 24:
        raise ValueError("forecast horizon must be within 24 hours")
    now = stamp(at)
    sync = (tip.get("depot") or {}).get("sync_time")
    try:
        age = (now - stamp(sync)).total_seconds()
    except (ValueError, TypeError):
        age = -1
    if not 0 <= age <= 3600:
        return {"status": "inventory_unverified", "production_enabled": False}
    decision = baseline.decide(tip)
    if decision.get("status") != "selected":
        return {"status": "inventory_unverified", "baseline": decision, "production_enabled": False}
    counts = tip["depot"]["counts"]
    stocks = {s: counts.get(i) for s, i in IDS.items()}
    if not all(number(x) and x >= 0 for x in stocks.values()):
        return {"status": "inventory_unverified", "production_enabled": False}
    stocks["shard"] = shard
    options = []
    gold = 0 if decision["gold_production_paused"] else 1
    for jade in range(decision["orundum_lines"] + 1):
        mode = f"jade{jade}_gold{gold}"
        item = {"mode": mode, "jade_trade": jade, "shard_mfg": jade,
                "gold_trade": 3 - jade, "gold_mfg": gold, "record_mfg": 3 - jade - gold}
        model = fitted.get("modes", {}).get(mode)
        if model:
            model_age = (now - stamp(model["observed_until"])).total_seconds()
            if 0 <= model_age <= 7 * 86400:
                item["forecast"] = forecast(stocks, model, horizon_hours, {"lmd": 1_500_000})
            else:
                item["forecast"] = {"status": "unknown", "reason": "rate_samples_stale"}
        else:
            item["forecast"] = {"status": "unknown", "reason": "mode_not_measured"}
        options.append(item)
    feasible = [x for x in options if x["forecast"]["status"] == "projected_feasible"]
    selected = max(feasible, key=lambda x: x["jade_trade"]) if feasible else options[-1]
    all_short = all(x["forecast"]["status"] == "projected_shortage" for x in options)
    runway = selected["forecast"].get("runway_hours", {})
    reviews = [v for v in runway.values() if v is not None]
    status = ("proposal" if feasible else "projected_shortage_review" if all_short
              else "baseline_only_need_measurements")
    return {"status": status, "selected": selected,
            "selected_projected_safe": bool(feasible),
            "next_review_in_hours": min(reviews) if reviews else None,
            "options": options, "baseline": decision, "stocks": stocks,
            "horizon_hours": horizon_hours, "production_enabled": False,
            "stamina_target": decision["stamina_target"],
            "note": "预测不是实机验收；保持活动理智优先，实际换产仍需六房核验。"}


def capacity_scenario(*, gold_mfg, jade_lines, hours, stocks, speeds,
                      gold_free_slots, shard_free_slots, trade_free_slots,
                      reserved_shard_jobs, pending_gold_demand,
                      pending_shard_demand, order_profile="ordinary_level3"):
    """Offline cycle budget with explicit assumptions; never choose/apply a plan.

    Room-slot arguments are PER ROOM, for homogeneous example rooms. Speed is
    a total multiplier (1.8 means +80%), not an operator bonus percentage.
    Factory slots hold items, trade slots hold orders. No intermediate pickup
    or delivery is assumed. Output remains unavailable until the next pickup.
    Reserved jobs have ALREADY had rock/LMD removed from Depot; count them once.
    Net balance below zero is a shortage, never actual negative inventory.
    """
    if (type(gold_mfg) is not int or type(jade_lines) is not int
            or not 0 <= jade_lines <= 2 or not 0 <= gold_mfg <= 3 - jade_lines):
        raise ValueError("invalid 333 manufacture counts")
    if not number(hours) or not 0 < hours <= 24:
        raise ValueError("cycle horizon must be within 24 hours")
    if order_profile != "ordinary_level3":
        return {"status": "needs_observations", "reason": "special_orders_need_actual_recipe",
                "production_enabled": False, "actual_balance_verified": False}
    required = set()
    if gold_mfg: required.add("gold_mfg")
    if jade_lines: required.update(("shard_mfg", "jade_trade"))
    if jade_lines < 3: required.add("gold_trade")
    if any(not number(speeds.get(k)) or speeds[k] <= 0 for k in required):
        raise ValueError("explicit positive effective speeds required")
    for value in (gold_free_slots, shard_free_slots, trade_free_slots,
                  reserved_shard_jobs, pending_gold_demand, pending_shard_demand):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("buffers, reserved jobs and pending demand must be nonnegative integers")
    for key in STOCKS:
        value = stocks.get(key)
        if value is not None and (not number(value) or value < 0):
            raise ValueError("stock must be known nonnegative or None")

    gm = speeds.get("gold_mfg", 0) / GOLD_HOURS
    sm = speeds.get("shard_mfg", 0) / SHARD_HOURS
    gt = speeds["gold_trade"] * GOLD_PER_ORDER / GOLD_ORDER_HOURS
    jt = speeds.get("jade_trade", 0) * 2 / JADE_ORDER_HOURS
    rates = {"gold_produced": gold_mfg * gm,
             "gold_demand": (3 - jade_lines) * gt,
             "shards_produced": jade_lines * sm,
             "shards_demand": jade_lines * jt}
    gross = {key: value * hours for key, value in rates.items()}
    limits = []
    if gold_mfg and gold_free_slots is not None:
        limits.append({"cause": "gold_factory_full", "hours": gold_free_slots / gm})
    if jade_lines and shard_free_slots is not None:
        limits.append({"cause": "shard_factory_full", "hours": shard_free_slots / sm})
    if trade_free_slots is not None:
        limits.append({"cause": "gold_order_queue_full_expected",
                       "hours": trade_free_slots * GOLD_ORDER_HOURS / speeds["gold_trade"]})
        if jade_lines:
            limits.append({"cause": "jade_order_queue_full",
                           "hours": trade_free_slots * JADE_ORDER_HOURS / speeds["jade_trade"]})

    raw_known = all(stocks.get(k) is not None for k in ("rock", "lmd"))
    jobs = (reserved_shard_jobs + min(floor(stocks["rock"] / 2), floor(stocks["lmd"] / 1600))
            if raw_known and reserved_shard_jobs is not None else None)
    if jade_lines and jobs is not None:
        limits.append({"cause": "shard_inputs_exhausted", "hours": jobs / rates["shards_produced"]})
    gp = (gold_mfg * min(floor(gm * hours + 1e-9), gold_free_slots)
          if gold_mfg and gold_free_slots is not None else 0 if not gold_mfg else None)
    sp = (jade_lines * min(floor(sm * hours + 1e-9), shard_free_slots)
          if jade_lines and shard_free_slots is not None else 0 if not jade_lines else None)
    # A finite material budget is shared by all shard factories, not repeated
    # independently for each room. Planned job allocation still needs live proof.
    if jade_lines:
        sp = min(sp, jobs) if sp is not None and jobs is not None else None
    gd = ((3 - jade_lines) * min(hours * speeds["gold_trade"] / GOLD_ORDER_HOURS,
                                trade_free_slots) * GOLD_PER_ORDER
          if trade_free_slots is not None else None)
    sd = (jade_lines * min(floor(hours * speeds.get("jade_trade", 0) / JADE_ORDER_HOURS + 1e-9),
                           trade_free_slots) * 2
          if jade_lines and trade_free_slots is not None else 0 if not jade_lines else None)
    deficits = {}
    for item, made, need, pending in (("gold", gp, gd, pending_gold_demand),
                                      ("shard", sp, sd, pending_shard_demand)):
        values = (stocks.get(item), made, need, pending)
        deficits[item] = (max(0, need + pending - stocks[item] - made)
                          if all(v is not None for v in values) else None)
    pending_deficits = {
        item: max(0, need - stocks[item]) if need is not None and stocks.get(item) is not None else None
        for item, need in (("gold", pending_gold_demand), ("shard", pending_shard_demand))
    }
    if gp is not None and sp is not None and gd is not None and sd is not None:
        caps_known = all(v is not None for v in deficits.values())
    else:
        caps_known = False
    limited = [x for x in limits if x["hours"] < hours]
    risk = any(v is not None and v > 0 for v in deficits.values()) or bool(limited)
    return {
        "status": "scenario_shortage_or_saturation" if risk else
                  "scenario_capacity_sufficient" if caps_known else "needs_observations",
        "production_enabled": False, "actual_balance_verified": False,
        "basis": "recipe_scenario_not_account_forecast", "sources": RECIPE_SOURCES,
        "horizon_hours": hours,
        "layout": {"jade_trade": jade_lines, "gold_trade": 3 - jade_lines,
                   "shard_mfg": jade_lines, "gold_mfg": gold_mfg,
                   "record_mfg": 3 - jade_lines - gold_mfg},
        "gross_per_hour": rates, "unconstrained_cycle": gross,
        "raw_inputs_for_full_shard_capacity": {"rock": gross["shards_produced"] * 2,
                                               "lmd": gross["shards_produced"] * 1600},
        "shard_jobs_with_free_and_reserved_inputs": jobs,
        "collectible_at_next_visit": {"gold": gp, "shard": sp},
        "new_order_demand_at_next_visit": {"gold_expected": gd, "shard": sd},
        "shortfall_after_collection_expected": deficits,
        "pending_order_shortfall_before_collection": pending_deficits,
        "limits": limits, "earliest_limit_hours": min((x["hours"] for x in limits), default=None),
        "unknowns": [name for name, value in (
            ("gold_buffer", gold_free_slots if gold_mfg else 0),
            ("shard_buffer", shard_free_slots if jade_lines else 0),
            ("trade_buffer", trade_free_slots), ("reserved_shard_jobs", reserved_shard_jobs if jade_lines else 0),
            ("gold_delivery", deficits["gold"]), ("shard_delivery", deficits["shard"] if jade_lines else 0))
            if value is None],
        "note": "产物需收取后交单；订单需求为普通三级订单期望。心情/效率变动、特殊订单、旧单、已预扣原料、实际容量与收货间隔须另核验。"
    }
