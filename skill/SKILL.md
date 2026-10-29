---
name: arknights-automation
description: "Control, diagnose, migrate, configure, recover, monitor, and verify AI-orchestrated Windows Arknights automation built on MAA and a supported emulator. Use when an AI agent must manage MAA beyond one-click tasks: autonomously find and advance unfinished mainline stages except tutorials, service Integrated Strategies reward tracks and permanent-growth points after settlement, route current events and mainline before fallback farming, apply inventory-driven base production, verify Security Service cap state, migrate to another Windows PC, fuse image/log evidence, recover interruptions or stale queues, enforce one controller, clean up, and report only verified results."
metadata:
  version: "1.1.1"
---

# MAA Arknights AI Control

Operate this project from its durable contract and current evidence. Never infer a new game goal merely because a technical action is convenient.

## Core capabilities beyond one-click MAA

- **Autonomous unfinished-mainline progression:** discover the current chapter/map frontier, classify the next unfinished node before acting, route battle nodes to an appropriate MAA job, handle verified story nodes through controlled navigation, prove completion, and continue. Tutorial stages are a manual handoff boundary.
- **Autonomous roguelike settlement service:** after a real exploration settlement, claim available level rewards, allocate permanent-growth points, verify marker/currency changes, return to the same theme, and resume the unchanged queue.
- **Evidence-gated daily orchestration:** verify weekly Annihilation, current-event availability, unfinished mainline scope, fallback-farm authority, Security Service cap state, and one final daily chain in that order; never let the final chain hide an earlier partial failure.
- **Adaptive service decisions:** read fresh inventory and reward state before selecting a project-approved base-production plan or short-circuiting a capped service. Stale values and entry-page success are not execution evidence.

The Skill includes both the workflow guidance and the existing custom execution source in `runtime/`: daily composition, mainline progression, roguelike settlement services, recognition, recovery and result handling. It is not a one-click installer. The receiving AI obtains publicly available third-party dependencies and adapts the existing execution interfaces to its own Windows environment. The user's account login, private production records and old task authorizations are not bundled. Start with [receiver-integration.md](references/receiver-integration.md) when transferring the package.

## Modular execution in v1

Use explicit task composition rather than an ever-growing chain of version wrappers. The orchestrator chooses authorized operations; each business module returns its own result; one shared runtime-service boundary supplies recognition and recovery; the outer host owns environment lifecycle and explicit exit work. A single-domain task must not silently call the full daily workflow or close the environment.

Keep game effects, completion-record persistence, exit/reward servicing, cleanup, and report verification separate. A failed record write is not permission to replay a successful battle. Render JSON, detailed text, and the final notification from the same reconciled, run-scoped ledger; GUI queue selection is not the whole-run business result.

Version 1.1.1 carries the existing execution source and reusable workflow contracts. The receiving machine still needs local interface and task binding; source inclusion does not transfer the author's account state or prove a new machine's runtime behavior.

## AI, MAA, and emulator boundary

- The AI layer owns intent compilation, environment discovery, sequencing, screenshot/OCR and log evidence fusion, progress records, failure classification, bounded recovery, truthful reporting, and cleanup.
- MAA owns its built-in task chains, Copilot execution, emulator connection, and supported game recognition/actions. Prefer MAA capabilities over reimplementing them.
- The project ADB layer fills verified gaps around game navigation, state confirmation, story/tutorial interruptions, and post-task evidence. It must not compete with an active MAA action stream.
- The emulator is the execution device. Its paths, instance, ADB port, package, and readiness are machine-local facts; its guest display is fixed at landscape 1920×1080 for this Skill.

This boundary is what makes the package an AI control Skill rather than a collection of fixed macros or an MAA usage guide.

## Start every task

1. Read the nearest `AGENTS.md` and its current role-specific resume pointers. Read the current summary of project state and the relevant contract, not the entire historical state. A workspace entry may link to an occupied implementation directory; use that implementation for scripts and relative dependencies instead of guessing a second root.
2. Use the project reasoning loop when the current project requires or provides it; otherwise keep the same minimum discipline: separate observed facts, inference, and unverified hypotheses.
3. Compile the current execution contract: target IDs, ordered steps, success evidence, failure transfer, prohibited substitutions, deadline, and control owner.
4. Resolve the selected runtime through the real launcher and its designated binding (for example, a project's `daily_runtime`), not a retained top-level legacy recipe or an expired special task. Normal execution and an explicitly selected live-validation candidate have different acceptance scopes; do not label the candidate fully verified or silently fall back to an old entry. Missing selection, out-of-scope use, dependency failure or fingerprint drift stops the affected action before mutation.
5. When the project has a component registry or protected-artifact fingerprint file, validate the selected component admission state and fingerprint before the first side effect. A mismatch blocks production; do not refresh the expected hash merely to make the gate pass.
6. Inspect the current process/queue/checkpoint state before changing anything. A visible window, running process, or completed shell command is not task success.

For a new installation with no project contract, use [PROJECT_CONTRACT.example.json](templates/PROJECT_CONTRACT.example.json) as a schema reference. Do not start real-account actions until the user has supplied or approved the active goals and resource policy.

Read [runtime-contract.md](references/runtime-contract.md) for authority and acceptance rules.

## Route the work

- For architecture refactoring, independent single-domain tasks, explicit composition, shared service installation, and host ownership, read [modular-architecture.md](references/modular-architecture.md). Its templates are inactive examples, not an execution plan to run automatically.
- For script-to-AI exception feedback, same-step resumption, safe-boundary pause/stop, deadline ownership and capability-scoped stability review, read [script-ai-cooperation.md](references/script-ai-cooperation.md). This is an adapter contract with bounded validation, not a bundled auto-repair or background-wakeup service.
- For session accounting, failed completion-record writes, false-negative verification, and consistent JSON/text/notification reports, read [result-ledger-and-reconciliation.md](references/result-ledger-and-reconciliation.md).
- For interrupted-run continuation, multi-phase events, cross-rotation settlement evidence, temporary-resource restoration, or scoped final reporting, read [continuation-and-closeout.md](references/continuation-and-closeout.md). Apply its checks to the affected domain without replaying verified effects or blocking unrelated authorized work.
- For transfer to another Windows PC, first read [receiver-integration.md](references/receiver-integration.md). Reuse the supplied custom execution logic; let the receiving AI discover/install third-party dependencies and bind its own environment. Read [windows-portability.md](references/windows-portability.md) only for the relevant connection or display details. The user logs in personally; installation does not require an extra identity check or a test battle.
- For scene classification, target candidates, action gates, post-action verification, run-scoped logs, multi-frame numeric reads, adaptive base decisions, and Security Service checks, read [recognition-and-service-gates.md](references/recognition-and-service-gates.md).
- For a daily full run, autonomous unfinished-mainline progression, event progression, stamina use, final reward cleanup, and shutdown, read [workflows.md](references/workflows.md).
- For Integrated Strategies reward tracks, permanent-growth trees, monthly/recollection teams, investigations, and settlement-boundary servicing, read [roguelike-rewards.md](references/roguelike-rewards.md).
- For MAA errors, emulator exits, update prompts, announcements, story/tutorial pages, queue stalls, log rotation, interpreter problems, cooldown, or duplicate supervisors, read [recovery-playbook.md](references/recovery-playbook.md).
- For a live queue, do only targeted, non-contending diagnostics. Do not run full offline regression or start a second controller.
- For source changes, patch the implementation directory and replay the actual defect at the final composed call site. New game actions need an authorized natural forward validation; pure verifier/report corrections reuse sealed same-run evidence without replaying gameplay. Keep source edit, launcher binding, loaded code and visible effect as separate claims. Sync packaged/installed copies only when requested.

## Windows portability invariant

Treat the workflow and evidence model as portable, but never copy this computer's absolute paths, ADB port, package name, or checkpoint locations to another PC without discovery. This automation deliberately standardizes the emulator guest at landscape `1920×1080`; it does not support coordinate rescaling. A different resolution is a preflight failure, not a reason to guess scaled taps.

## Evidence hierarchy

Prefer direct evidence in this order:

1. Game screenshot/OCR or visible result screen.
2. MAA Core task-chain evidence and GUI queue state.
3. Supervisor checkpoint and project state.
4. Process/window presence.
5. Assistant inference.

Use fresh, run-scoped evidence. Old logs, a single ambiguous OCR frame, a successful click, or entry into the right page cannot prove the current result. When a number controls resource use or completion, require a labeled region and stable repeated reading or an independent corroborating source.

Treat a conflict by preserving the higher evidence and investigating the lower layer. Never convert `TaskChainError`, queue end, or process death directly into a game defeat or completion.

Daily and long-running modes are separate contracts. Do not automatically start or resume Integrated Strategies, Reclamation, or another long-running queue merely because the daily chain ended. A separately authorized long-running queue must share the controller lock and yield at its declared cleanup boundary.

## Safe recovery rule

Classify before acting:

- Ordinary game outcome: continue according to the active contract; do not consume the technical retry budget.
- Verified recoverable UI interruption: clear it through the project ADB/screenshot path, confirm the page changed, then resume without consuming the technical retry budget.
- Technical failure: diagnose and use the current task's bounded retry, cooldown and deadline policy; do not invent universal retry counts. For an adapter that supports cooperation, preserve the live deadline owner, request AI help, recheck fresh state and resume only the failed step. A technical repair does not reset battle/resource budgets or replay completed work.
- Unknown state: preserve evidence and pause the affected action instead of inventing clicks or changing the goal. Retain deadline cleanup; independent authorized work may continue only if it does not contend for the same controller.

Never silently change theme, task type, stage, difficulty, team, resource use, retry cap, or stop condition.

## Finish

Report what was actually completed, failed, deferred, and still running. Include decisive evidence, cleanup state, and the next recoverable checkpoint. Update the project's existing state entry when one is provided; do not create a second state file merely to match a guessed path. Record a lesson only when the root cause is proven.
