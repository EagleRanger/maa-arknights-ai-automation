# Recovery playbook

## First classify the incident

An invalid command shape, stale observation number or missing diagnostic field
before any game action is an **input/coordination error**, not a game failure.
Have the command adapter fill mechanical counters from its current receipt;
reject/resynchronize a bad instruction without clicking or closing the healthy
game. Use the project's existing bounded retries/AI feedback if it still cannot
proceed. Do not wire a minor parser error straight to whole-run cleanup.
This does not remove account/resource/ownership boundaries or permit replay of
an action whose commit is uncertain. Components return their own result; the
outer coordinator decides continuation and final shutdown.

Use the current screenshot/OCR, MAA Core tail, GUI queue state, checkpoint, and process list together.

### Verified UI interruption

Known recoverable pages include:

- MAA update announcement: scroll the announcement body to the bottom, select "下次公告更新前不再显示", confirm, and verify the main MAA UI returns.
- Game login/update notice: dismiss only validated controls and verify the terminal or home page returns.
- First-emulator tutorial: use the existing project handler and verify the tutorial overlay disappears.
- Roguelike first-clear/ending story: MAA may emit `TaskChainError` after the ending while the game shows story text plus `跳过` or `自动 OFF`. Skip/advance the story through the ADB screenshot path, confirm the page is no longer `story`, and resume without incrementing technical restarts.
- Mid-stage story segment: advance it only when the stage-specific flow and on-screen evidence confirm this is the blocker.

Never repeatedly restart MAA against an unchanged story page.

For client/resource updates and new sign-in skins, use
[continuity-and-signin.md](continuity-and-signin.md). A received reward overlay
may still need closing; do not erase a proved reward or repeat its claim.

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

Follow the current project's explicit retry, cooldown and deadline policy; do not impose a universal number of restarts or a one-hour wait. Stop only the faulty owned queue when needed and safe, preserve its save and evidence, and repair the verified cause before resuming the same remaining objective. Keep a healthy game instance open when the repair can reuse it. Reconcile effects first: a preparation failure or parser error is not a spent battle attempt, and a technical continuation must not replay completed daily work. Repeating the same failure without new evidence is not recovery.

### Ordinary game outcome

If several unrelated daily chains fail at the same home/entry template, inspect
their shared raw frame and resource/theme compatibility before rerunning each
chain. This is a common-entry failure, not several independent battle failures.

Integrated Strategies defeat, a non-perfect stage result, or a completed exploration is not automatically technical. Record it as gameplay evidence and follow the active phase policy. Never use a normal defeat to change theme, difficulty, core operator, retries, or objective.

## Recurrent recent-week checks

1. Ensure there is one supervisor and one MAA queue owner.
2. Confirm the actual Python interpreter has `rapidocr_onnxruntime`, `uiautomation`, and `cv2`; do not trust the command name alone.
3. Confirm MAA resource/client versions after an update and handle the announcement before queue setup.
4. Bind Core evidence to the active run's start time and controller identity, accounting for rotation. If callbacks flush only on exit, the latest callback file may belong to the previous run; inspect the active live log or terminal instead.
5. Distinguish GUI `queue already running` from a fresh start failure.
6. If a checkpoint is stale, reconcile it with current MAA/game evidence instead of replaying old progress.
7. At the hard deadline, stop the MAA queue first, then close game, MAA, MuMu, and owned log windows; verify they are gone.

## Recovery evidence

A recovery is complete only when all applicable checks pass:

- the blocking page changed;
- the same MAA contract is still configured;
- Core begins the intended task chain;
- the intended theme/subtasks and real page progress are seen beyond startup, rather than a repeated click loop;
- the checkpoint advances with a current timestamp;
- no second controller is alive.
