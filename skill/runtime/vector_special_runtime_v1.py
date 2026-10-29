"""Per-process portable binding for the bounded VEC#3 execution probe.

Bindings in another Python process never carry over. Import this facade in
every short-lived navigation/copilot/log command, instead of importing the
legacy module without rebinding. No game action occurs during binding.
"""
from pathlib import Path
import json
from maa_portable_runtime_v1 import PORTABLE_ROOT, bind


def sync_device(module):
    """Read the selected VM port in every fresh process; no GUI/game writes."""
    if module.resolve_mumu_instance() is None:
        return False  # An offline VM may subsequently be launched by ensure_env.
    reply = module._run_mumu("info", "-v", module.MUMU_VM_INDEX, timeout=10)
    if reply.returncode != 0:
        return False
    info = json.loads(reply.stdout or "{}")
    port = info.get("adb_port")
    if type(port) is not int or not 1024 <= port <= 65535:
        return False
    device = "127.0.0.1:" + str(port)
    if module.DEVICE != device:
        module.DEVICE = device
        module._close_maacore_screenshot_bridge()
    return True


def runtime(module=None):
    if module is None:
        import arknights_auto as module
    proof = bind(module)
    expected = Path(PORTABLE_ROOT).resolve()
    if Path(module.MAA_ROOT).resolve() != expected:
        raise RuntimeError("VEC portable runtime binding did not apply")
    if Path(module.MAA_PATH).resolve() != expected / "MAA.exe":
        raise RuntimeError("VEC executable does not match bound resources")
    # Bind() does not carry a DEVICE from a different Python process. Forgetting
    # a separate detect call repeatedly caused tap/shot to use old port 16384.
    sync_device(module)
    from vector_environment_startup_v1 import install
    install(module)
    return module


def start_copilot(job_path):
    a = runtime()
    return a.run_maa_copilot(str(Path(job_path).resolve()))
