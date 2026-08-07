# Windows portability and first-run baseline

## Conclusion and support boundary

The automation model is portable to ordinary Windows gaming PCs, but the current project implementation is not a zero-configuration portable binary. Its workflow, evidence gates, MAA queue control, ADB screenshot path, retry classification, and cleanup rules can be reused. Machine-specific paths, emulator instance/port, game package, Python runtime, and writable output locations must be discovered on every new PC.

Supported baseline:

- Windows 10 or Windows 11, 64-bit, with an interactive signed-in desktop session;
- one supported Android emulator instance and one MAA controller for the target account;
- MuMu 12 is the verified reference emulator; other MAA-supported emulators require their own launcher and ADB discovery adapter;
- emulator guest fixed at landscape `1920×1080`, 16:9;
- MAA, emulator, game client, and Python/OCR dependencies installed and readable;
- network access when MAA resources, updates, or external copilot jobs are required.

Do not claim another PC is supported merely because MAA opens. The minimum acceptance is a fresh ADB screenshot with exact dimensions, a valid game-package check, successful OCR imports, a single controller, and a non-destructive navigation verification. A real battle remains a separate authorized test.

Official MAA references:

- [MAA new-user requirements](https://docs.maa.plus/zh-cn/manual/newbie.html) state that Windows support is Windows 10/11 and emulator resolution should be landscape 1280×720 or 1920×1080.
- [MAA connection settings](https://docs.maa.plus/zh-cn/manual/connection.html) document automatic ADB detection, MuMu's multiple possible ports, and manual ADB/configuration choices.
- MAA task resources use a 1280×720 design base and scale internally. This project does not rely on that scaling for its own fixed ADB coordinates; it standardizes the emulator at 1920×1080 instead.

## Non-negotiable display profile

Use this exact emulator profile for this Skill:

| Item | Required value | Why |
| --- | --- | --- |
| Guest orientation | Landscape | Game UI and all project ROIs assume landscape. |
| Guest screenshot | `1920×1080` | Project ADB coordinates, ROIs, completion badges, leak marker, and navigation fallbacks were validated at this size. |
| Aspect ratio | `16:9` | Required by MAA recognition and project layout assumptions. |
| Game display cutout adaptation | `0` when the client exposes it | Avoids shifting the game UI away from expected ROIs. |
| Emulator density/DPI | Record it; do not use it as the primary gate | The verified MuMu instance reports physical density 280, but the decisive gate is the actual ADB screenshot being 1920×1080. |
| Windows desktop scaling | Prefer 100% for first calibration | ADB screenshots/taps are unaffected. UI Automation is normally scale-safe, but any desktop-coordinate fallback must be recalibrated if Windows scaling is not 100%. |

If the screenshot is 1280×720, 2560×1440, rotated, letterboxed, or cropped, stop. Change MuMu to 1920×1080 and restart the game. Do not add coordinate multiplication as a quick fix.

Android `wm size` may report the panel's physical dimensions as `1080x1920` even while the game screenshot is landscape 1920×1080. Gate on the captured PNG dimensions, not the text order from `wm size` alone.

## Verified reference machine profile

This is evidence for comparison, not a portable configuration to copy blindly:

| Item | Current verified value |
| --- | --- |
| Emulator | MuMu 12 |
| ADB executable | `C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe` |
| Current ADB device | `127.0.0.1:16384` |
| Android physical size report | `1080x1920` |
| Android physical density | `280` |
| Actual game screenshot contract | landscape `1920×1080` |
| Android version | `12` |
| Game package | Bilibili client `com.hypergryph.arknights.bilibili` |
| MAA executable | `%LOCALAPPDATA%\MAA-App\MAA.exe` |
| Verified Python capability | 64-bit Python with `PIL`, `cv2`, `rapidocr_onnxruntime`, and `uiautomation` importable |

The port `16384` is not a constant. MuMu multi-instance ports can change; discover the running instance every time. The official mainland package is commonly `com.hypergryph.arknights`, while this reference account uses the Bilibili package. Detect or configure the package explicitly before launch/force-stop operations.

## First-run inventory

Before controlling a new PC, record these values in a machine-local profile or environment variables. Never write another person's username or this PC's paths into shared Skill instructions.

1. Windows version/build and architecture.
2. Emulator product, installation root, launcher/CLI path, instance ID, and actual ADB executable.
3. Exactly one target ADB device/port and its status (`device`, not `offline` or `unauthorized`).
4. Captured PNG width/height, Android density, Android version, and orientation.
5. Installed Arknights package and server/client type.
6. MAA executable, config directory, Core log, GUI log, version, and connection profile.
7. Python executable and successful imports for `PIL`, `cv2`, `rapidocr_onnxruntime`, and `uiautomation`.
8. Writable project/output/checkpoint/log directories.
9. Windows desktop scaling and whether any desktop-coordinate fallback is enabled.
10. Current process owner: no second supervisor, no second MAA queue, and no unrelated ADB device participating in auto-detection.

Use `scripts/check-windows-environment.ps1` for a read-only inventory. Pass explicit paths when auto-discovery is ambiguous. It must not start the game, change resolution, install dependencies, or enter a battle.

## Recommended machine-local configuration

Keep machine values outside business rules and source logic. Prefer a local profile or environment variables such as:

- `ARKNIGHTS_ADB`
- `ARKNIGHTS_DEVICE`
- `ARKNIGHTS_GAME_PACKAGE`
- `ARKNIGHTS_MUMU_ROOT`
- `ARKNIGHTS_MAA_PATH`
- `ARKNIGHTS_PYTHON`
- `ARKNIGHTS_AUTO_BASE`

The current project still contains reference-machine defaults. A portable launcher should resolve values in this order: explicit current-run parameter, machine-local profile/environment, safe discovery, then a clearly labeled reference default. Discovery returning zero or multiple candidates is a preflight failure.

## Permission and process rules

- Run MAA and the supervisor at the same Windows privilege level. Elevation mismatch can hide or disable UI Automation controls.
- Do not install MAA under a location that requires UAC writes for normal updates. Keep its directory writable by the current user.
- Use an interactive desktop session for MAA GUI/UI Automation. A locked session or non-interactive scheduled task is not equivalent to a visible signed-in desktop.
- Use ADB screenshots and Android input for game control. Use Windows UI Automation only for MAA controls and validated desktop dialogs; avoid foreground mouse takeover.
- Keep one emulator instance, one MAA process/queue, and one supervisor per account unless a multi-instance contract explicitly assigns separate ports and directories.
- Taskbar ghost thumbnails are not proof of duplicate processes. Verify process IDs first; a non-disruptive taskbar redraw is cosmetic cleanup only.

## Layered acceptance on another PC

1. **Inventory:** all paths, package, device, output directories, and interpreter resolve uniquely.
2. **Display gate:** a fresh ADB PNG is exactly 1920×1080 and recognizable; no rotation or letterboxing.
3. **Static UI recognition:** OCR identifies a known home/terminal marker from the fresh screenshot; no clicks yet.
4. **Safe input:** one authorized non-resource navigation tap is followed by a screenshot proving the intended page transition.
5. **MAA control:** UI Automation finds the real `MAA.exe` window by process ownership, configures the intended task, and Core logs the exact task chain.
6. **Small real run:** only with current authorization, run one low-risk contracted action and verify the game result, Core log, checkpoint, and cleanup separately.

Syntax tests, imports, preflight, a running process, or an MAA queue start do not prove the full automation works on the new PC.

## Symptom-to-cause checklist

| Symptom | First checks |
| --- | --- |
| OCR boxes or clicks are shifted | Fresh PNG dimensions, rotation, letterboxing, game cutout setting; enforce 1920×1080. |
| ADB cannot connect | Discover MuMu's current port, ensure exactly one target, reject `offline`/`unauthorized`, avoid stale fixed 16384 assumptions. |
| Game will not launch/stop | Verify server-specific package name before `monkey` or `am force-stop`. |
| MAA controls cannot be found | Confirm the window belongs to real `MAA.exe`, same privilege level, update/announcement dialog cleared, and UIA runtime installed. |
| Screenshot works but gestures fail | Check ADB return code/stderr and MAA touch mode; do not treat a rejected input as a successful click. |
| Recognition works but fixed desktop click misses | Remove desktop-coordinate fallback or calibrate it at the current Windows scaling/window geometry. |
| Duplicate windows or queue contention | Inspect real process IDs, single-instance lock, queue state, and checkpoint before launching anything. |
| MAA update repeatedly blocks startup | Complete/recover the update, scroll and dismiss the announcement once, then revalidate client/resource version and Core logs. |
| Python starts but OCR crashes | Verify the exact interpreter imports all four required modules; do not trust `python` on PATH or a WindowsApps stub. |
| Logs show old completion | Select the newest log by modification time, record the current run boundary, and account for rotation. |

## Portability verdict

- **Portable now:** contract compilation, task ordering, evidence hierarchy, ADB-first game control, MAA queue monitoring, technical/ordinary-failure separation, transaction-safe config changes, single-instance supervision, reporting, and cleanup rules.
- **Portable after first-run discovery:** MuMu/MAA/Python paths, ADB device/port, package name, log/checkpoint locations, and UI Automation window selection.
- **Not portable by design:** arbitrary emulator resolutions or aspect ratios. This Skill requires 1920×1080 landscape.
- **Not yet proven automatically on every emulator:** launcher/instance management beyond the verified MuMu 12 adapter. Other MAA-supported emulators need a separately verified adapter even if MAA itself supports them.
