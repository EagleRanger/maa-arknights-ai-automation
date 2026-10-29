"""Bounded YW node input; transport timeout is not UI failure or a battle.

Only opens ordinary YW detail. Does not click Start, consume sanity, reconnect
ADB, restart its server, or interfere with an active MaaCore task queue.
"""
import re
import subprocess

from daily_fast_proxy_yw_v1 import page_kind


def open_detail(app, original, event, display_name, *, tag="event_detail", ensure_map=True):
    if not re.fullmatch(r"YW-[1-8]", str(display_name)):
        return original(event, display_name, tag=tag, ensure_map=ensure_map)
    if app._maa_task_queue_running():
        return None
    if ensure_map and not app.goto_event_map(event):
        return None
    path, items, pos = app._locate_event_stage(display_name, event=event)
    if not pos:
        return None
    proof = app._RUN_SUMMARY.setdefault("event", {}).setdefault("node_input", [])

    def observe(label):
        frame = app.shot(f"{tag}_{display_name}_{label}")
        rows = app.ocr(frame)
        text = " ".join(str(t) for t, _, _ in rows)
        confirmed = app._event_stage_detail_confirmed(text, display_name, rows)
        return frame, rows, text, confirmed

    # Reuse fresh locate evidence. Never send cached coordinates from a prior
    # run; a second input is allowed only if two settled frames are still map.
    for attempt in range(2):
        if app._maa_task_queue_running():
            return None
        receipt = dict(stage=display_name, attempt=attempt+1, map_evidence=path,
                       position=list(pos), transport_timeout_seconds=15)
        proof.append(receipt)
        try:
            result = subprocess.run(
                [app.ADB, "-s", app.DEVICE, "shell", "input", "tap", str(pos[0]), str(pos[1])],
                timeout=15, capture_output=True, text=True,
            )
            output = (result.stdout or "") + (result.stderr or "")
            if result.returncode or "SecurityException" in output or "INJECT_EVENTS" in output:
                receipt.update(status="input_rejected", detail=output[:240])
                return None
            receipt["transport"] = "returned"
        except subprocess.TimeoutExpired:
            receipt["transport"] = "timeout_outcome_unknown"
        app.wait(4)
        frame, rows, text, confirmed = observe("settled")
        receipt["settled_evidence"] = frame
        if confirmed:
            receipt["status"] = "target_detail_verified"
            return frame, rows, text
        kind, _ = page_kind(rows)
        next_pos = app._event_stage_position(rows, display_name)
        if attempt or kind != "yw_map" or not next_pos or not app._event_stage_marker_reliable(next_pos):
            receipt["status"] = "target_not_confirmed_no_replay"
            return None
        app.wait(2)
        frame2, rows2, text2, confirmed2 = observe("second_readback")
        receipt["second_evidence"] = frame2
        if confirmed2:
            receipt["status"] = "late_target_detail_verified"
            return frame2, rows2, text2
        kind2, _ = page_kind(rows2)
        pos2 = app._event_stage_position(rows2, display_name)
        if kind2 != "yw_map" or not pos2 or not app._event_stage_marker_reliable(pos2):
            receipt["status"] = "page_changed_no_replay"
            return None
        receipt["status"] = "settled_map_relocate_once"
        app.log(f"[活动点击] {display_name}尚在地图，两帧确认后重新定位补点一次", "WARN")
        path, items, pos = frame2, rows2, pos2
    return None


def install(app):
    original = app._open_event_stage_detail

    def open_event_stage_detail(event, display_name, *, tag="event_detail", ensure_map=True):
        return open_detail(app, original, event, display_name, tag=tag, ensure_map=ensure_map)

    app._open_event_stage_detail = open_event_stage_detail
    return app
