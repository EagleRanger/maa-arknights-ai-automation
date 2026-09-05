# Project workflows

## Daily full run

Use the exact priority in the discovered `PROJECT_CONTRACT.json`; do not hard-code yesterday's event or chapter.

Typical phase boundaries are:

1. Start and clear validated update/login/announcement blockers.
2. Verify weekly Annihilation first when the current week is incomplete. If its stamina-consuming flow fails, block later stamina use but continue safe non-stamina cleanup when the contract permits it.
3. Inspect the current terminal/event surface before spending stamina. Distinguish no event, an executable current event, an event with no compatible job, discovery failure, and unknown navigation.
4. Validate every recorded todo against the current game state. Repair stale progress instead of replaying a task already proved complete.
5. Complete the authorized current event; otherwise verify and advance unfinished mainline scope. Missing operators, unsupported recording/manual jobs, and invalid job selection are not battle defeats.
6. Use a contracted fallback farm only when current evidence shows no higher-priority executable event and all applicable mainline or hidden branches are verified complete. Never infer this from an old progress record.
7. Check the current Security Service cycle. A proved capped state is an accepted no-action result; an uncapped cycle requires a separately validated earning handler.
8. Read fresh inventory, select only a project-approved base-production plan, then run exactly one final startup/base/recruit/store/reward chain. If inventory is stale or unreadable, preserve the current product state.
9. Reconcile current-run stamina, tasks, rewards, failures, and cleanup. Show one truthful final report, then close owned game/MAA/emulator/log windows unless a separately authorized long-running queue already owns the next window.

## Autonomous unfinished-mainline progression

This is the primary improvement over a fixed MAA stage script. Do not require the user to name every next node when the active contract already authorizes continued mainline progression.

1. Start from a fresh chapter/map screenshot and reconcile it with the current progress record. Never reuse yesterday's assumed frontier.
2. Discover the next unfinished authorized node from visible map topology and completion markers. If the selected chapter is complete, navigate through the verified chapter/map path and continue discovery.
3. Classify the node before handing control to MAA:
   - story node: use the verified skip/advance path and require the map completion marker after returning;
   - normal, H, or other supported battle node: select a job compatible with that exact node and hand battle execution to MAA;
   - tutorial node: pause and request manual completion; do not guess tutorial taps or treat it as a normal battle;
   - unknown/special node: preserve evidence and use only a separately validated handler.
4. For a battle node, distinguish missing operators, support-unit requirements, invalid job selection, Core failure, and real battle failure. Trying the same unchanged job repeatedly is not strategy variation.
5. After every node, return to the map and prove completion with the node's validated marker or result evidence. Story nodes may have only a map-completion marker and no battle badge.
6. Advance the frontier only from current evidence, then repeat discovery. Stop on the contracted goal, hard deadline, tutorial/manual boundary, unknown node, exhausted authorized retries, or resource-policy boundary.
7. Keep normal, H, and special branches as separate evidence scopes. Completion of one branch is not proof that the chapter is fully complete.

When exact node colors or symbols differ across chapters, use the validated structural detector for that chapter/mode. A plausible color match alone is not purchase or completion authority.

## Recent production safeguards

- Before the first real action, require the project's admitted component and protected-fingerprint gate to pass. Fingerprint drift is a production blocker, even if a narrower recipe still passes.
- If an activity is absent from the terminal card, a verified activity-calendar route may be used only as a fallback; visually confirm the intended stage family before battle.
- Aggregate completion evidence across the same game day. A later cleanup process must not overwrite earlier completed phases with a smaller last-process report.
- A targeted daily chain may perform its documented cold-start environment bootstrap, but its final report must name the actual scope run. Never present a targeted Award or base repair as a full daily completion.
- Keep accepted production and validation-only candidates under separate immutable identities. Offline tests or a partial live path do not authorize a production-pointer switch.
- An unavailable or unsupported event route is not the same as no current event. Preserve the unfinished event and follow only its approved transfer.
- Read decisive numeric state from labeled regions and stable repeated frames or an independent source. Do not backfill current stamina, inventory, reward, or cap values from old logs.
- If no farm target is authorized, do not invent one merely to spend sanity.

## Long-running modes

Daily and long-running queues are separate contracts. Do not mix their checkpoints or completion claims.

For Integrated Strategies:

- read the active theme and phase from the contract;
- inherit only generic recovery/reward/deadline rules, not another theme's recruitment or deployment overlays;
- ordinary exploration defeat can count as growth only when the active phase says so;
- reward claims require direct reward-marker change;
- distinguish the theme's reward track from its permanent-growth tree; after every eligible real settlement, autonomously claim available rewards and allocate available permanent-growth points, verify the named currency or marker changed, return to the same theme home, and resume the unchanged queue;
- use one supervisor, a current checkpoint, bounded technical recovery, and the contract-defined cleanup boundary before the next daily owner takes control; do not auto-chain this mode after a daily run.

For Reclamation Algorithm:

- use its dedicated checkpoint and reward target;
- stop MAA through its normal stop control before exiting a looping run;
- treat scheduled refreshes as recoverable UI transitions, not completion.

## Change and validation

1. Patch the source implementation, preserving user changes and backups.
2. Run syntax checks and the smallest tests covering the defect.
3. If no live queue is active, run proportionate offline regression.
4. Perform a real forward-path verification with screenshots/Core/checkpoint evidence.
5. Synchronize any assistant/runtime copy only after source validation and compare hashes.
6. Update project state and evidence-backed lessons. Never claim deployment from file creation alone; verify the recipient/runtime actually received or loaded it.
