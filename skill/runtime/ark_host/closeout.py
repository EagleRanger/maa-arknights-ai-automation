"""Persistent, once-per-session normal exit; not another daily execution."""
from dataclasses import asdict
from pathlib import Path

from ark_modules.core import ReceiptStore
from ark_modules.runtime_bindings import PreparedRuntimePort


def finish_session(host, context, output, *, drone_policy=None, previous_collection=None):
    if context.owner != host.owner:
        raise ValueError('exit belongs to a different controller')
    output = Path(output)
    store = ReceiptStore(output/'exit.json')
    identity = asdict(context)
    state = store.load() or {'context': identity}
    if state['context'] != identity:
        raise ValueError('exit receipt belongs to a different session')
    if state.get('finished'):
        return dict(state, reused=True)
    if host._close_receipt is not None:
        return {'status': 'unknown', 'detail': 'environment already closed without this exit receipt',
                'cleanup': host._close_receipt}

    def collect_once():
        if 'tail' in state:
            old = state['tail']
            return (dict(old, status='unknown', needs_reconciliation=True)
                    if old.get('status') == 'running' else old)
        state['tail'] = {'status': 'running'}
        store.save(state)
        port = PreparedRuntimePort(host.app, output/'modules', owns_control=host.owns,
                                   operations=['daily.exit_tail'])
        port.now = host.clock
        result = port.execute('daily.exit_tail', {'drone_policy': drone_policy or {},
                             'previous_collection': previous_collection}, context, {})
        state['tail'] = asdict(result)
        store.save(state)
        return state['tail']

    host.before_close = collect_once
    state['cleanup'] = host.close()
    tail = state['cleanup'].get('exit_tail')
    if tail is not None: state['tail'] = tail
    state['finished'] = state['cleanup'].get('status') != 'deferred'
    state['status'] = ('succeeded' if state['cleanup'].get('verified') is True
                       and (state.get('tail') or {}).get('status') == 'succeeded' else 'partial')
    state['controller_released'] = host.release() if state['finished'] else False
    if not state['controller_released']: state['status'] = 'partial'
    store.save(state)
    return state
