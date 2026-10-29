"""V22 MuMu startup and cleanup admission for the daily workflow.

This adapter leaves the frozen V21 runtime untouched.  It makes the MuMu/ADB
environment boundary explicit and testable before the legacy business flow is
allowed to continue.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable


MUMU_UI_PROCESSES = (
    "MuMuPlayer.exe",
    "MuMuNxMain.exe",
    "MuMuNxDevice.exe",
    "MuMuVMMHeadless.exe",
)


class EnvironmentStartupAbort(BaseException):
    """Bypass the legacy inner ``except Exception`` fallback safely."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class ProcessProbe:
    names: frozenset[str]
    source: str
    errors: tuple[str, ...] = ()


def _redacted_summary(value: Any, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(
        r"(?i)(token|authorization|api[_-]?key|secret)(\s*[:=]\s*)[^\s,;]+",
        r"\1\2<redacted>",
        text,
    )
    return text[:limit] + ("..." if len(text) > limit else "")


def _json_payload(text: str, *, allow_empty: bool) -> Any:
    raw = (text or "").strip()
    if not raw:
        if allow_empty:
            return None
        raise ValueError("empty_json_output")
    return json.loads(raw)


def _payload_error(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("errcode", "error_code", "errorCode"):
        if key in payload:
            try:
                if int(payload[key]) != 0:
                    return f"{key}={payload[key]}"
            except (TypeError, ValueError):
                return f"{key}={payload[key]!r}"
    if payload.get("success") is False:
        return "success=false"
    if payload.get("ok") is False:
        return "ok=false"
    return None


def _instance_info(payload: Any, vm_index: str) -> dict[str, Any]:
    if isinstance(payload, dict) and (
        "is_android_started" in payload or "is_process_started" in payload
    ):
        return payload
    rows: Iterable[Any]
    if isinstance(payload, dict):
        rows = payload.values()
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("mumu_info_shape_invalid")
    candidates = [item for item in rows if isinstance(item, dict)]
    for item in candidates:
        if str(item.get("index")) == str(vm_index):
            return item
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(f"mumu_instance_not_found:{vm_index}")


def _adb_device_online(stdout: str, device: str) -> bool:
    for line in (stdout or "").splitlines():
        fields = line.strip().split()
        if len(fields) >= 2 and fields[0] == device:
            return fields[1].lower() == "device"
    return False


def _launch_and_require_ready(
    runtime: Any,
    original_run_mumu: Callable[..., Any],
    args: tuple[Any, ...],
    *,
    timeout: int,
    polls: int = 24,
    interval: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
):
    result = original_run_mumu(*args, timeout=timeout)
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    rc = int(getattr(result, "returncode", -1))
    runtime.log(
        "  [V22/MuMu] launch rc=%s stdout=%s stderr=%s"
        % (rc, _redacted_summary(stdout), _redacted_summary(stderr))
    )
    if rc != 0:
        raise EnvironmentStartupAbort(
            "mumu_launch_nonzero",
            f"rc={rc}; stderr={_redacted_summary(stderr)}",
        )
    try:
        launch_payload = _json_payload(stdout, allow_empty=True)
    except (ValueError, json.JSONDecodeError) as exc:
        raise EnvironmentStartupAbort("mumu_launch_output_invalid", str(exc)) from exc
    payload_error = _payload_error(launch_payload)
    if payload_error:
        raise EnvironmentStartupAbort("mumu_launch_json_error", payload_error)

    try:
        marker = list(args).index("--vmindex")
        vm_index = str(args[marker + 1])
    except (ValueError, IndexError):
        vm_index = str(runtime._resolve_mumu_vm_index())

    android_seen = False
    adb_port_seen = None
    last_detail = "no poll completed"
    for attempt in range(max(1, polls)):
        info_result = original_run_mumu(
            "info", "--vmindex", vm_index, timeout=min(timeout, 10)
        )
        info_rc = int(getattr(info_result, "returncode", -1))
        info_stdout = getattr(info_result, "stdout", "") or ""
        info_stderr = getattr(info_result, "stderr", "") or ""
        if info_rc != 0:
            last_detail = f"info rc={info_rc}; stderr={_redacted_summary(info_stderr)}"
        else:
            try:
                payload = _json_payload(info_stdout, allow_empty=False)
                payload_error = _payload_error(payload)
                if payload_error:
                    raise ValueError(payload_error)
                info = _instance_info(payload, vm_index)
                process_started = bool(info.get("is_process_started", False))
                android_started = bool(info.get("is_android_started", False))
                port = int(info.get("adb_port") or 0)
                last_detail = (
                    f"process={process_started}; android={android_started}; adb_port={port}"
                )
                if process_started and android_started:
                    android_seen = True
                    if port > 0:
                        adb_port_seen = port
                        device = f"127.0.0.1:{port}"
                        runtime.subprocess.run(
                            [runtime.ADB, "connect", device], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=5,
                        )
                        adb_result = runtime.subprocess.run(
                            [runtime.ADB, "devices"], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=8,
                        )
                        if (
                            int(getattr(adb_result, "returncode", -1)) == 0
                            and _adb_device_online(
                                getattr(adb_result, "stdout", "") or "", device
                            )
                        ):
                            runtime.DEVICE = device
                            runtime.log(
                                f"  [V22/MuMu] 双门通过: vm={vm_index}, device={device}"
                            )
                            return result
                        last_detail = f"android ready; adb device not online: {device}"
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                last_detail = f"info output invalid: {exc}"
        if attempt + 1 < max(1, polls):
            sleep(interval)

    if android_seen and adb_port_seen:
        raise EnvironmentStartupAbort("mumu_adb_not_ready", last_detail)
    raise EnvironmentStartupAbort("mumu_android_not_started", last_detail)


def _fallback_process_probe(
    *, psutil_module: Any = None,
    powershell_runner: Callable[..., Any] = subprocess.run,
) -> ProcessProbe:
    errors: list[str] = []
    if psutil_module is None:
        try:
            import psutil as psutil_module  # type: ignore[no-redef]
        except Exception as exc:  # pragma: no cover
            errors.append(f"psutil:{type(exc).__name__}:{exc}")
            psutil_module = False
    if psutil_module is not False:
        try:
            names = {
                str(proc.info.get("name") or "")
                for proc in psutil_module.process_iter(["name"])
                if proc.info.get("name")
            }
            return ProcessProbe(frozenset(names), "psutil", tuple(errors))
        except Exception as exc:
            errors.append(f"psutil:{type(exc).__name__}:{exc}")
    try:
        command = "Get-Process | ForEach-Object { $_.ProcessName + '.exe' }"
        result = powershell_runner(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        if int(getattr(result, "returncode", -1)) != 0:
            raise RuntimeError(_redacted_summary(getattr(result, "stderr", "")))
        names = {line.strip() for line in (result.stdout or "").splitlines() if line.strip()}
        return ProcessProbe(frozenset(names), "get-process", tuple(errors))
    except Exception as exc:
        errors.append(f"get-process:{type(exc).__name__}:{exc}")
        raise RuntimeError("; ".join(errors)) from exc


def _cleanup_probe(runtime: Any, original_run_mumu: Callable[..., Any]) -> dict[str, Any]:
    vm_index = str(runtime._resolve_mumu_vm_index())
    cli_status: dict[str, Any] = {"source": "mumu-cli", "verified": False}
    try:
        result = original_run_mumu("info", "--vmindex", vm_index, timeout=10)
        if int(getattr(result, "returncode", -1)) != 0:
            raise RuntimeError(
                f"rc={result.returncode}; stderr={_redacted_summary(result.stderr)}"
            )
        info = _instance_info(
            _json_payload(getattr(result, "stdout", "") or "", allow_empty=False), vm_index
        )
        cli_status.update(
            verified=True,
            is_process_started=bool(info.get("is_process_started", False)),
            is_android_started=bool(info.get("is_android_started", False)),
        )
    except Exception as exc:
        cli_status["error"] = f"{type(exc).__name__}: {exc}"
    snapshot = runtime._tasklist_snapshot()
    lower = snapshot.lower()
    remaining = [name for name in MUMU_UI_PROCESSES if name.lower() in lower]
    probe = {
        "status": "PASS", "vm_index": vm_index, "cli": cli_status,
        "processes": {"verified": True, "remaining": remaining},
    }
    if remaining:
        probe.update(status="FAIL", reason="mumu_process_residue")
    elif cli_status.get("verified") and (
        cli_status.get("is_process_started") or cli_status.get("is_android_started")
    ):
        probe.update(status="FAIL", reason="mumu_cli_instance_still_started")
    elif not cli_status.get("verified"):
        probe.update(status="FAIL", reason="mumu_cli_cleanup_unverified")
    return probe


def install(runtime: Any) -> Any:
    if getattr(runtime, "_daily_environment_gate_v22_installed", False):
        return runtime
    original_run_mumu = runtime._run_mumu
    original_ensure_env = runtime.ensure_env
    original_tasklist_snapshot = runtime._tasklist_snapshot
    original_capture_stamina = runtime._capture_stamina_observation
    original_cleanup = runtime.cleanup_after_task

    def tasklist_snapshot_v22():
        try:
            return original_tasklist_snapshot()
        except Exception as exc:
            probe = _fallback_process_probe()
            runtime.log(
                f"  [V22/cleanup] tasklist不可用({exc}); 改用{probe.source}", "WARN"
            )
            return "\n".join(sorted(probe.names))

    def run_mumu_v22(*args, timeout=30):
        normalized = tuple(str(item) for item in args)
        if "control" in normalized and "launch" in normalized:
            return _launch_and_require_ready(
                runtime, original_run_mumu, normalized, timeout=timeout
            )
        return original_run_mumu(*args, timeout=timeout)

    def ensure_env_v22():
        try:
            ready = original_ensure_env()
        except EnvironmentStartupAbort as exc:
            runtime._RUN_SUMMARY["environment_startup"] = {
                "status": "failed", "reason": exc.reason, "detail": exc.detail,
            }
            runtime._RUN_SUMMARY.setdefault("flow_control", {}).update(
                status="paused", reason="environment_startup_failed"
            )
            runtime.log(
                f"⛔ 环境启动失败并终止业务导航: {exc.reason}: {exc.detail}", "ERROR"
            )
            return False
        if ready:
            runtime._RUN_SUMMARY["environment_startup"] = {
                "status": "ready", "device": runtime.DEVICE,
            }
        return ready

    def capture_stamina_v22(label, *args, **kwargs):
        env = runtime._RUN_SUMMARY.get("environment_startup") or {}
        if env.get("status") == "failed":
            runtime._RUN_SUMMARY.setdefault("stamina_observations", {})[str(label)] = {
                "status": "skipped_environment_startup_failed"
            }
            runtime.log(f"  [V22] 环境失败，跳过{label}理智截图")
            return None
        return original_capture_stamina(label, *args, **kwargs)

    def cleanup_v22(*args, **kwargs):
        env = runtime._RUN_SUMMARY.get("environment_startup") or {}
        if env.get("status") == "failed":
            kwargs["check_badges"] = False
        original_cleanup(*args, **kwargs)
        probe = _cleanup_probe(runtime, original_run_mumu)
        runtime._RUN_SUMMARY["cleanup_multisource"] = probe
        if probe["status"] != "PASS":
            raise RuntimeError(
                f"V22多源清理核验失败: {probe.get('reason')}: "
                + json.dumps(probe, ensure_ascii=False)
            )
        runtime.log("  [V22/cleanup] MuMu CLI与进程双源清理核验通过")

    runtime._tasklist_snapshot = tasklist_snapshot_v22
    runtime._run_mumu = run_mumu_v22
    runtime.ensure_env = ensure_env_v22
    runtime._capture_stamina_observation = capture_stamina_v22
    runtime.cleanup_after_task = cleanup_v22
    runtime._daily_environment_gate_v22_installed = True
    return runtime

