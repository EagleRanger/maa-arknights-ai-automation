"""Honor a verified completed daily goal at the post-run badge boundary."""

from daily_completed_goal_freeze_v24 import find_same_day_completed_goal


def install(runtime):
    if getattr(runtime, "_daily_frozen_cleanup_v25_installed", False):
        return runtime
    original = runtime.check_and_clear_badges

    def guarded_badges(*args, **kwargs):
        prior = runtime._RUN_SUMMARY.get("daily_goal_freeze") or {}
        if prior.get("status") == "frozen_same_day_complete" and prior.get("reentry_prevented") is True:
            # Recheck day and later Fight evidence at the actual mutation boundary.
            current = find_same_day_completed_goal(runtime)
            if current.get("status") == "frozen_same_day_complete":
                runtime._RUN_SUMMARY["post_daily_badges"] = {
                    "status": "skipped_completed_goal",
                    "live_badges_checked": False,
                    "base_entered": False,
                    "game_day": current["game_day"],
                    "completed_at": current["completed_at"],
                    "latest_fight_at": current.get("latest_fight_at"),
                    "segment_sha256": current["segment_sha256"],
                }
                runtime.log("  [V25] 最终日常完成证据仍有效，跳过任务/基建角标页面操作，继续进程清理")
                return None
        return original(*args, **kwargs)

    guarded_badges._daily_frozen_cleanup_v25 = True
    runtime.check_and_clear_badges = guarded_badges
    runtime._daily_frozen_cleanup_v25_installed = True
    return runtime
