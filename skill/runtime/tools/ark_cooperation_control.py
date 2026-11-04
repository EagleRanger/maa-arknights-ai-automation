"""Read/pause/recheck an existing owned run; never launches game or daily."""
import argparse
import json
from pathlib import Path
import sys
import uuid
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_host.cooperation_v1 import atomic_json, read_message, write_reply


def process_alive(pid):
    """One read-only exact-PID query; never signal a Windows process."""
    if type(pid) is not int or pid <= 0:
        return None
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False if ctypes.get_last_error() == 87 else None
    try:
        code = wintypes.DWORD()
        return (code.value == 259) if kernel.GetExitCodeProcess(handle, ctypes.byref(code)) else None
    finally:
        kernel.CloseHandle(handle)


def brief(output, run_id, state, alive=process_alive):
    coop = state.get('cooperation') or {}
    event = read_message(coop.get('event_path', '')) if coop.get('event_path') else {}
    closed = bool(state.get('finished_at'))
    running = alive(state.get('controller_pid'))
    return dict(run_id=run_id, status=state.get('status'), finished_at=state.get('finished_at'),
        controller_pid=state.get('controller_pid'), controller_alive=running,
        event_id=coop.get('event_id'), phase=coop.get('phase'), created_at=event.get('created_at'),
        reason=(coop.get('failure') or {}).get('reason'), event_path=coop.get('event_path'),
        evidence=((coop.get('failure') or {}).get('observation') or {}).get('evidence', []),
        delivery_status=event.get('delivery_status'), cleanup_finished=state.get('cleanup_finished'),
        next_action='report_terminal_only' if closed else (
            'send_native_feedback_now' if state.get('status') == 'waiting_for_ai' and running is True
            else 'verify_host_then_send'), response_path=str(output / 'ai_response.json'))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--action', choices=('status', 'brief', 'pause_at_boundary', 'stop_at_boundary', 'recheck', 'stop'), default='status')
    p.add_argument('--event-id')
    a = p.parse_args()
    output = Path(a.output).resolve()
    manifest = read_message(output / 'run.json')
    if manifest.get('run_id') != a.run_id:
        p.error('run identity mismatch')
    state = read_message(output / 'checkpoint.json')
    if a.action == 'brief':
        print(json.dumps(brief(output, a.run_id, state), ensure_ascii=False, indent=2))
        return 0
    if a.action == 'status':
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    if state.get('finished_at') or manifest.get('finished_at'):
        p.error('closed run cannot be resumed')
    if a.action in ('recheck', 'stop'):
        if a.event_id != (state.get('cooperation') or {}).get('event_id'):
            p.error('current event identity mismatch')
        write_reply(output, run_id=a.run_id, event_id=a.event_id,
                    response_id=uuid.uuid4().hex, action=a.action)
    else:
        atomic_json(output / 'control_request.json', dict(
            run_id=a.run_id, request_id=uuid.uuid4().hex, action=a.action))
    print('request_written_not_yet_applied')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
