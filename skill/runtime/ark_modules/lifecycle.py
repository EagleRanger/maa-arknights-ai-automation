"""Day-level finalisation only. Workers receive none of these callbacks."""
from dataclasses import asdict


class DayFinaliser:
    def __init__(self, *, observe_final, close_owned_environment, verify_closed, publish_report,
                 verify_day_complete=None):
        self.observe_final = observe_final
        self.close_owned_environment = close_owned_environment
        self.verify_closed = verify_closed
        self.publish_report = publish_report
        self.verify_day_complete = verify_day_complete

    def __call__(self, results):
        # Daily rewards belong to daily_tasks. Closing the environment never
        # adds an implicit Award, a badge click, or another full daily run.
        errors = []
        try:
            final = self.observe_final()
            if not isinstance(final, dict):
                raise TypeError('final observation must be a record')
        except Exception as exc:
            final = {"verified": False, "reason": str(exc)}
            errors.append("最终余额未核验")
        try:
            self.close_owned_environment()
        except Exception as exc:
            errors.append("关闭环境失败：" + str(exc))
        try:
            cleanup = self.verify_closed()
            if not isinstance(cleanup, dict):
                raise TypeError('cleanup verification must be a record')
        except Exception as exc:
            cleanup = {"verified": False, "reason": str(exc)}
        complete = bool(results) and all(r.status == "succeeded" for r in results.values())
        # Finishing a base-only plan is not finishing a day. Whole-day acceptance
        # must come from the current compiled daily goal contract, not this sink.
        daily_complete = False
        if complete and self.verify_day_complete is not None:
            try:
                daily_complete = self.verify_day_complete(results) is True
            except Exception as exc:
                errors.append("整日验收失败：" + str(exc))
        balance = final.get('value', final.get('sanity'))
        final_verified = (final.get('verified') is True and bool(final.get('evidence'))
                          and type(balance) is int and balance >= 0)
        # A true goal predicate or all green submodules cannot replace the
        # actual final balance or cleanup. Keep unknown balance unknown.
        daily_complete = daily_complete and final_verified and cleanup.get('verified') is True and not errors
        receipt = {"module_results": {key: asdict(value) for key, value in results.items()},
                   "requested_tasks_complete": complete, "daily_complete": daily_complete,
                   "final_observation": final,
                   "final_observation_verified": final_verified,
                   "cleanup": cleanup, "cleanup_verified": cleanup.get("verified") is True,
                   "errors": errors}
        # Existing evidence-bound formatter/notifier is supplied by the total
        # coordinator. Exactly one invocation, after verification of cleanup.
        self.publish_report(receipt)
        return receipt
