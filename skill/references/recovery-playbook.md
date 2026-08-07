# Recovery playbook

## First classify the incident

Use the current screenshot/OCR, MAA Core tail, GUI queue state, checkpoint, and process list together.

### Verified UI interruption

Known recoverable pages include:

- MAA update announcement: scroll the announcement body to the bottom, select "下次公告更新前不再显示", confirm, and verify the main MAA UI returns.
- Game login/update notice: dismiss only validated controls and verify the terminal or home page returns.
- First-emulator tutorial: use the existing project handler and verify the tutorial overlay disappears.
- Roguelike first-clear/ending story: MAA may emit `TaskChainError` after the ending while the game shows story text plus `跳过` or `自动 OFF`. Skip/advance the story through the ADB screenshot path, confirm the page is no longer `story`, and resume without incrementing technical restarts.
- Mid-stage story segment: advance it only when the stage-specific flow and on-screen evidence confirm this is the blocker.

Never repeatedly restart MAA against an unchanged story page.

### Technical failure

Examples:

- MAA process or Core dies while no ordinary settlement is visible;
- task queue vanishes before a verified outcome;
- `TaskChainError` remains after recoverable UI pages are excluded;
- emulator/device/ADB becomes unavailable;
- wrong interpreter lacks project OCR/UI packages;
- MAA update leaves a partial installation or incompatible client/resource state;
- rotated logs make the monitor read stale completion evidence;
- duplicate supervisors or a stale single-instance owner contend for the same queue.

Apply at most three fast recoveries. Each recovery should stop the owned queue if needed, reload the same configured environment, and verify it is ready. After the fourth consecutive technical failure, clean the owned UI/processes, preserve the checkpoint, wait one hour, and retry the unchanged contract if before the deadline.

### Ordinary game outcome

Integrated Strategies defeat, a non-perfect stage result, or a completed exploration is not automatically technical. Record it as gameplay evidence and follow the active phase policy. Never use a normal defeat to change theme, difficulty, core operator, retries, or objective.

## Recurrent recent-week checks

1. Ensure there is one supervisor and one MAA queue owner.
2. Confirm the actual Python interpreter has `rapidocr_onnxruntime`, `uiautomation`, and `cv2`; do not trust the command name alone.
3. Confirm MAA resource/client versions after an update and handle the announcement before queue setup.
4. Read the newest Core log by modification time and account for log rotation.
5. Distinguish GUI `queue already running` from a fresh start failure.
6. If a checkpoint is stale, reconcile it with current MAA/game evidence instead of replaying old progress.
7. At the hard deadline, stop the MAA queue first, then close game, MAA, MuMu, and owned log windows; verify they are gone.

## Recovery evidence

A recovery is complete only when all applicable checks pass:

- the blocking page changed;
- the same MAA contract is still configured;
- Core begins the intended task chain;
- the queue remains active beyond the immediate startup window;
- the checkpoint advances with a current timestamp;
- no second controller is alive.
