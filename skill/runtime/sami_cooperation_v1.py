"""Opt-in normal Sami control adapter. Does not replace frozen daily gameplay."""
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from ark_host.cooperation_v1 import ControlExit, CooperativeControl


@contextmanager
def boundary(sami, app, *, packet, deadline, output, event_output, **test_clock):
    checkpoint = sami.write_checkpoint
    cleanup = sami.cleanup
    control = CooperativeControl(
        run_id=packet['run_id'], output=output, event_output=event_output,
        deadline=deadline.timestamp(), queue_idle=lambda: app._maa_task_queue_running() is False,
        save=checkpoint, **test_clock)

    def write(state):
        control.state = state
        return checkpoint(state)

    def home_recheck():
        # Narrow first release: no blind back/click/claim while diagnosing.
        image, _, text = sami.page('sami_ai_resume_readonly')
        return dict(ok=sami.is_sami_home(text), read_only=True,
                    evidence=[str(image)] if image else [],
                    text=text[:3000],
                    reason='sami_home_rechecked' if sami.is_sami_home(text) else 'page_not_yet_reconciled')

    control.observe = home_recheck

    def hold_cleanup(state, status, detail):
        control.state = state
        if status != 'deadline_stopped' and not control.exit_reason:
            # Unexpected errors also keep the host alive. They cannot be retried
            # from an unwound stack; project supplies a validated restart later.
            try:
                control.wait_for_repair('host_exception', {'reason': status, 'detail': detail},
                    lambda: dict(ok=False, read_only=True,
                                 reason='new_candidate_or_explicit_stop_required'))
            except ControlExit:
                pass
        final_status = control.exit_reason or status
        if control.exit_reason and str(state.get('error', '')).startswith('ControlExit:'):
            state['control_exit'] = state.pop('error')
        state.setdefault('cooperation', {}).update(
            status=final_status, cleanup_requested=True)
        return cleanup(state, final_status,
            '到点收尾；未完成内容见cooperation' if final_status == 'deadline_stopped' else detail)

    originals = {name: getattr(sami, name) for name in (
        'establish_sami_home', 'service_expedition_records', 'service_culture', 'drain_safe_settlement')}
    depth = [0]

    def guarded(name):
        def call(*args, **kwargs):
            # Reward/culture services call navigation internally. Keep ONE
            # failure incident at the outer semantic step, not recursive waits.
            if depth[0]:
                return originals[name](*args, **kwargs)
            def operation():
                depth[0] += 1
                try:
                    return originals[name](*args, **kwargs)
                finally:
                    depth[0] -= 1
            return control.step(name, operation, home_recheck)
        return call

    original_mode = app.mode_roguelike
    def mode(*args, **kwargs):
        control.before_next_round(home_recheck)
        return original_mode(*args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(sami, 'write_checkpoint', write))
        stack.enter_context(patch.object(sami, 'cleanup', hold_cleanup))
        for name in originals:
            stack.enter_context(patch.object(sami, name, guarded(name)))
        stack.enter_context(patch.object(app, 'mode_roguelike', mode))
        yield control
