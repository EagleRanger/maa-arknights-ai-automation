"""Local evidence publication; never runs or repeats a game operation.

Human descriptions are not state keys. A failed projection is repairable from
the immutable source and cannot erase a completed effect or suppress cleanup.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import tempfile


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest().upper()


def publish_json(path, value, *, immutable=False):
    """Serialize before touching disk, atomic commit, then read back.

    Identical retries are no-ops. Conflicting sealed evidence is never replaced.
    A unique sibling temp file prevents unrelated writes sharing .tmp names.
    """
    path = Path(path)
    data = encoded(value)
    if path.exists():
        previous = path.read_bytes()
        if previous == data:
            return dict(path=str(path), sha256=digest(data), reused=True)
        if immutable:
            raise ValueError('immutable_record_conflict: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            try:
                os.link(temporary, path)  # exclusive publish, never replace a racing writer
            except FileExistsError:
                if path.read_bytes() != data:
                    raise ValueError('immutable_record_conflict: ' + str(path))
        else:
            os.replace(temporary, path)
        if path.read_bytes() != data:
            raise OSError('record_readback_mismatch: ' + str(path))
        return dict(path=str(path), sha256=digest(data), reused=False)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def finish_completed_scope(receipt, *, record, exit_tail, checkpoint):
    """Separate bookkeeping from the already-authorized post-task tail.

    Exceptions from either stage are classified independently. Interrupts are
    intentionally propagated to the owner's final cleanup, not swallowed.
    """
    receipt['business_status'] = 'completed_verified'
    for name, operation in (('completion_record', record), ('exit', exit_tail)):
        try:
            value = operation()
            if not isinstance(value, dict) or value.get('status') not in {
                    'succeeded', 'failed', 'blocked', 'partial', 'interrupted'}:
                raise ValueError(name + '_invalid_result_contract')
            receipt[name] = deepcopy(value)
        except Exception as exc:
            receipt[name] = dict(status='failed', error=f'{type(exc).__name__}: {exc}')
        try:
            checkpoint(receipt)
        except Exception as exc:
            receipt.setdefault('record_errors', []).append(
                dict(stage=name, error=f'{type(exc).__name__}: {exc}'))
    receipt['status'] = ('completed' if not receipt.get('record_errors') and all(
        receipt[name]['status'] == 'succeeded' for name in ('completion_record', 'exit')) else 'partial')
    return receipt


def settle_owner(receipt, host):
    """Keep cleanup/release failures separate and always produce a terminal state."""
    if host.acquired:
        try:
            receipt['cleanup'] = host.close()
        except Exception as exc:
            receipt['cleanup'] = dict(verified=False, status='unknown', error=f'{type(exc).__name__}: {exc}')
        try:
            receipt['controller_released'] = host.release() is True
        except Exception as exc:
            receipt['controller_released'] = False
            receipt['release_error'] = f'{type(exc).__name__}: {exc}'
    if receipt.get('status') != 'interrupted' and (receipt.get('cleanup', {}).get('verified') is not True
                                               or receipt.get('controller_released') is not True):
        receipt['status'] = 'partial'
    return receipt
