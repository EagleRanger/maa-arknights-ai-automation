"""MAA trade assistance follows the pending-order card across the row.

No new template/click coordinate: enlarge only the original order-row ROI.
The Oct5 B102 source screenshot matches at (720,464), outside the old ROI.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import hashlib
import json

OLD_ROI = [250, 430, 460, 120]
ROW_ROI = [250, 430, 1000, 120]


def corrected_tasks(tasks):
    result = deepcopy(tasks)
    task = result['DroneAssistTrade']
    if task.get('action') != 'ClickSelf' or task.get('roi') not in (OLD_ROI, ROW_ROI):
        raise ValueError('Unrecognized MAA trade assistance schema; retain resource')
    task['roi'] = list(ROW_ROI)
    return result


@contextmanager
def resource_boundary(runtime, output):
    """Idle entry, readback, original bytes restored after the queue settles."""
    if runtime._maa_task_queue_running() is True:
        raise RuntimeError('Active MAA queue owns resources')
    path = Path(runtime.MAA_ROOT) / 'resource/tasks/tasks.json'
    original = path.read_bytes()
    source = json.loads(original.decode('utf-8-sig'))
    fixed = corrected_tasks(source)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    backup = output / 'tasks.before_drone_roi.json'
    # The current pristine source is retained once, not overwritten on retry.
    if not backup.exists():
        backup.write_bytes(original)
    runtime._atomic_write_json(str(path), fixed)
    if json.loads(path.read_text(encoding='utf-8-sig')) != fixed:
        raise RuntimeError('Trade ROI resource readback mismatch')
    receipt = {'old_roi': source['DroneAssistTrade']['roi'], 'new_roi': ROW_ROI,
               'source_sha256': hashlib.sha256(original).hexdigest().upper(),
               'source_backup': str(backup), 'changed_only': 'DroneAssistTrade.roi',
               'restored': False}
    runtime._atomic_write_json(str(output / 'roi_receipt.json'), receipt)
    try:
        yield receipt
    finally:
        if runtime._maa_task_queue_running() is True:
            raise RuntimeError('MAA still active; defer resource restoration')
        path.write_bytes(original)
        receipt['restored'] = path.read_bytes() == original
        runtime._atomic_write_json(str(output / 'roi_receipt.json'), receipt)
