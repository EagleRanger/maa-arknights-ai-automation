"""Headless MaaCore screenshot bridge for MuMu 12.

This module deliberately exposes capture only.  It does not launch the MAA GUI,
append a task, send input, or alter the game state.
"""

from __future__ import annotations

import ctypes
import io
import json
import os
import threading
from pathlib import Path


class MaaCoreScreenshotError(RuntimeError):
    pass


def decode_maacore_image(payload: bytes, width: int, height: int):
    """Decode MaaCore's encoded image or legacy raw BGR into the target size."""
    from PIL import Image

    expected = int(width) * int(height) * 3
    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            image = source.convert("RGB")
    except Exception:
        if len(payload) < expected:
            raise MaaCoreScreenshotError(
                "AsstGetImage既非编码图像也不是完整BGR: "
                f"{len(payload)} < {expected}"
            )
        image = Image.frombytes(
            "RGB", (int(width), int(height)), payload[:expected], "raw", "BGR"
        )

    source_size = image.size
    if image.size != (int(width), int(height)):
        source_ratio = image.width / max(1, image.height)
        target_ratio = int(width) / max(1, int(height))
        if abs(source_ratio - target_ratio) > 0.01:
            image.close()
            raise MaaCoreScreenshotError(
                f"截图宽高比异常: {source_size} != {(int(width), int(height))}"
            )
        resized = image.resize(
            (int(width), int(height)), Image.Resampling.LANCZOS
        )
        image.close()
        image = resized
    return image, source_size


class MaaCoreScreenshotBridge:
    """Reuse MaaCore's official MuMu screenshot-extra path without MAA.exe."""

    def __init__(
        self,
        install_root: str,
        adb_path: str,
        address: str,
        emulator_path: str,
        user_dir: str,
        width: int = 1920,
        height: int = 1080,
    ) -> None:
        self.install_root = os.path.abspath(install_root)
        self.adb_path = os.path.abspath(adb_path)
        self.address = str(address)
        self.emulator_path = os.path.abspath(emulator_path)
        self.user_dir = os.path.abspath(user_dir)
        self.width = int(width)
        self.height = int(height)
        self._lock = threading.Lock()
        self._dll_cookie = None
        self._core = None
        self._handle = None
        self.last_source_size = None

    def _bind_api(self) -> None:
        if self._core is not None:
            return
        dll_path = os.path.join(self.install_root, "MaaCore.dll")
        if not os.path.isfile(dll_path):
            raise MaaCoreScreenshotError(f"MaaCore.dll不存在: {dll_path}")
        if hasattr(os, "add_dll_directory"):
            self._dll_cookie = os.add_dll_directory(self.install_root)
        core = ctypes.WinDLL(dll_path)
        core.AsstSetUserDir.argtypes = [ctypes.c_char_p]
        core.AsstSetUserDir.restype = ctypes.c_uint8
        core.AsstLoadResource.argtypes = [ctypes.c_char_p]
        core.AsstLoadResource.restype = ctypes.c_uint8
        core.AsstSetConnectionExtras.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        core.AsstSetConnectionExtras.restype = None
        core.AsstCreate.argtypes = []
        core.AsstCreate.restype = ctypes.c_void_p
        core.AsstDestroy.argtypes = [ctypes.c_void_p]
        core.AsstConnect.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
        ]
        core.AsstConnect.restype = ctypes.c_uint8
        core.AsstAsyncScreencap.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
        core.AsstAsyncScreencap.restype = ctypes.c_int32
        core.AsstGetImage.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64]
        core.AsstGetImage.restype = ctypes.c_uint64
        self._core = core

    def connect(self) -> None:
        with self._lock:
            if self._handle:
                return
            self._bind_api()
            Path(self.user_dir).mkdir(parents=True, exist_ok=True)
            core = self._core
            if not core.AsstSetUserDir(os.fsencode(self.user_dir)):
                raise MaaCoreScreenshotError("AsstSetUserDir失败")
            if not core.AsstLoadResource(os.fsencode(self.install_root)):
                raise MaaCoreScreenshotError("AsstLoadResource失败")
            extras = json.dumps(
                {"path": self.emulator_path},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            core.AsstSetConnectionExtras(b"MuMuEmulator12", extras)
            handle = core.AsstCreate()
            if not handle:
                raise MaaCoreScreenshotError("AsstCreate失败")
            if not core.AsstConnect(
                handle,
                os.fsencode(self.adb_path),
                self.address.encode("utf-8"),
                b"MuMuEmulator12",
            ):
                core.AsstDestroy(handle)
                raise MaaCoreScreenshotError(f"MaaCore连接失败: {self.address}")
            self._handle = handle

    def capture_png(self, path: str) -> str:
        """Capture one frame and save it under the legacy 1920x1080 contract."""
        with self._lock:
            if not self._handle:
                # connect() also takes the lock, so initialize outside the locked retry.
                pass
        if not self._handle:
            self.connect()
        with self._lock:
            call_id = self._core.AsstAsyncScreencap(self._handle, 1)
            if call_id <= 0:
                raise MaaCoreScreenshotError("AsstAsyncScreencap失败")
            expected = self.width * self.height * 3
            buffer = ctypes.create_string_buffer(expected)
            got = int(self._core.AsstGetImage(self._handle, buffer, expected))
            if got <= 0:
                raise MaaCoreScreenshotError("AsstGetImage未返回图像")
            payload = buffer.raw[:got]
            # MaaCore 6.16.8 returns an encoded PNG/JPEG payload whose byte
            # length is much smaller than width*height*3. Older bindings may
            # expose raw BGR instead, so retain that compatibility path.
            image, self.last_source_size = decode_maacore_image(
                payload, self.width, self.height
            )
            try:
                image.save(path, format="PNG")
            finally:
                image.close()
            return path

    def close(self) -> None:
        with self._lock:
            if self._handle and self._core:
                self._core.AsstDestroy(self._handle)
            self._handle = None
            self._core = None
            if self._dll_cookie:
                self._dll_cookie.close()
            self._dll_cookie = None

    def __enter__(self) -> "MaaCoreScreenshotBridge":
        self.connect()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()
