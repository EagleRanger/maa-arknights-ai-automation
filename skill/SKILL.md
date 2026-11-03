---
name: arknights-automation
description: "Control, diagnose, migrate, configure, recover, monitor, and verify AI-orchestrated Windows Arknights automation built on MAA and a supported emulator. Use when an AI agent must manage MAA beyond one-click tasks: first-time setup on another Windows PC, daily full runs, event or mainline progression, Integrated Strategies or Reclamation Algorithm supervisors, image/log evidence fusion, MAA update/announcement/story interruptions, stale queues, cooldown recovery, duplicate controllers, final cleanup, and evidence-backed project retrospectives."
metadata:
  version: "1.2.1"
---

# MAA Arknights AI Control

本包是含执行源码的 **v1.2.1**。默认保留已发布的 `run_daily_v146.full()` 与原推图链；`run_daily_v153.full()` 是接收方可选择的新组合，不因安装自动切换。兑换、模组与专精中的待完善功能标为“测试”。代码对接见 [接收方说明](references/receiver-integration.md)，直接复用 `runtime/`。

Operate this project from its durable contract and current evidence. Never infer a new game goal merely because a technical action is convenient.

## AI, MAA, and emulator boundary

- Keep the project's proven navigator and per-stage loop in control of daily execution, including switching jobs and checking the real result. AI handles unfamiliar pages and exceptions; it is not a second watcher of a healthy run.
- Invoke MAA as a plugin for the specific task it supports (for example Copilot battle or reading a training room). Do not switch back and forth just because MAA also offers its own daily workflow. Borrow a proven MAA recognition action when it closes a real gap.
- The project's background input path keeps ownership of existing navigation, state checks and recovery. It must not issue input during an active MAA action stream.
- The emulator is the execution device. Its paths, instance, ADB port, package, and readiness are machine-local facts; its guest display is fixed at landscape 1920×1080 for this Skill.

This boundary is what makes the package an AI control Skill rather than a collection of fixed macros or an MAA usage guide.

## Start every task

1. Read the nearest `AGENTS.md` and follow its current project-loop/contract pointers and role-specific resume bundle. An entry directory may link to an occupied implementation directory; use that implementation for scripts and relative dependencies. Do not load all historical state or infer missing files from a guessed location.
2. Use the project reasoning loop when the current project requires or provides it; otherwise keep the same minimum discipline: separate observed facts, inference, and unverified hypotheses.
3. Compile the current execution contract: target IDs, ordered steps, success evidence, failure transfer, prohibited substitutions, deadline, and control owner.
4. Inspect the current process/queue/checkpoint state before changing anything. A visible window, running process, or completed shell command is not task success.
5. Read verified facts for the currently identified game account through [account-progress.md](references/account-progress.md). Use those facts to select work, then feed verified effects back into that same account store. Shared Skill rules are not somebody else's account progress.

For a new installation with no project contract, use [PROJECT_CONTRACT.example.json](templates/PROJECT_CONTRACT.example.json) as a schema reference. Do not start real-account actions until the user has supplied or approved the active goals and resource policy.

On first installation, use [first-run-features.md](references/first-run-features.md)
to confirm the recipient's account/environment, resource boundaries and optional
modules once. Keep the **previously published daily/progression chain** as the
default; this update does not redesign its order or require the user to assemble
a new chain. Save recipient choices privately and let their own AI adjust them
through the existing module interfaces. Do not repeat setup before every daily
run, or copy the publisher's account targets/settings into the recipient profile.

Read [runtime-contract.md](references/runtime-contract.md) for authority and acceptance rules.

For unchanged continuation within the same task, reuse the accepted contract
and launcher selection and read the current brief/run delta. Do not repeatedly
reload the launcher source, full handoff or long history before the next known
action. Recheck the affected fields when user scope, selected artifacts,
identity, control ownership or direct evidence changes.

## Route the work

- For first-time setup, migration to another Windows PC, changed emulator/MAA/Python paths, ADB connection changes, or resolution/input problems, read [windows-portability.md](references/windows-portability.md) and run the read-only environment check before any real-account action.
- For a daily full run, event/mainline progression, stamina use, final reward cleanup, and shutdown, read [workflows.md](references/workflows.md).
- For Integrated Strategies reward tracks, permanent-growth trees, monthly/recollection teams, investigations, and settlement-boundary servicing, read [roguelike-rewards.md](references/roguelike-rewards.md).
- For account-specific completion memory, repeated already-complete work, or portable progress feedback, use [account-progress.md](references/account-progress.md) and the bundled `scripts/account_progress_v1.py` store; game adapters still own UI verification.
- For operator mastery, module missions, or green/yellow/red voucher exchange, read [operator-and-voucher-interfaces.md](references/operator-and-voucher-interfaces.md). Native capability, a wired project adapter and a live-verified result are different states. Confirm actual operator/module progress before finding work; do not treat a started training or a won battle as a completed development goal.
- 本版增量：干员培养、模组任务、凭证兑换按上面各自的 **Beta** 边界使用；当期逐日开放的附加任务和刷取后的领奖见 [日常与活动流程](references/workflows.md)。未配置的可选项跳过，不拦原有日常。接收方若只有本 Skill 源目录而没有相应运行模块，应报告缺少该模块，不能仅凭说明声称已经执行。
- For a training shortlist from recent idle-play Copilots, use the dated stage sample and fixed-core counts in that same reference. For an equipped module use the read-only [operator badge reader](scripts/operator_module_badge.py) on the actual character page; it does not operate the game.
- For MAA errors, emulator exits, update prompts, announcements, story/tutorial pages, queue stalls, log rotation, interpreter problems, cooldown, or duplicate supervisors, read [recovery-playbook.md](references/recovery-playbook.md).
- For interrupted daily continuation, user-completed substeps, game updates, new sign-in layouts or unknown-page handoff, read [continuity-and-signin.md](references/continuity-and-signin.md). A local failure or absent user reply does not cancel the authorized remainder.
- For a tutorial without a compatible job, use [tutorial-ai.md](references/tutorial-ai.md): AI first follows current deployment/facing instructions; only an unresolved AI attempt requests human play. Publish this capability as “教学关代理逻辑（测试）”.
- For OCR conflicts, reward/status misclassification, balance-versus-battle discrepancies, or final-report corrections, read [evidence-validation.md](references/evidence-validation.md). Diagnose the producing layer before changing a model or retrying gameplay.
- For daily release notices or a user-requested upgrade, read [release-notices-and-local-merge.md](references/release-notices-and-local-merge.md). Daily runs only append a version notice to the existing final report; upgrades are requested through the recipient's own AI conversation, never an automatic overwrite.
- For a live queue, do only targeted, non-contending diagnostics. Do not run full offline regression or start a second controller.
- For source changes, patch the implementation directory, replay the actual failure, and test the final composed call path as well as the module. Reuse sealed game evidence for a pure verifier/report correction; new navigation or action behavior still needs a natural authorized live validation. Update project records, then sync a packaged/runtime copy only when requested.

## Windows portability invariant

Treat the workflow and evidence model as portable, but never copy this computer's absolute paths, ADB port, package name, or checkpoint locations to another PC without discovery. This automation deliberately standardizes the emulator guest at landscape `1920×1080`; it does not support coordinate rescaling. A different resolution is a preflight failure, not a reason to guess scaled taps.

Distinguish the guest's ADB frame from MAA's internally rescaled `1280×720`
recognition frame. The latter is normal, not evidence that the emulator changed
resolution; never reuse its coordinates as raw ADB taps.

## Evidence hierarchy

Prefer direct evidence in this order:

1. Game screenshot/OCR or visible result screen.
2. MAA Core task-chain evidence and GUI queue state.
3. Supervisor checkpoint and project state.
4. Process/window presence.
5. Assistant inference.

Treat a conflict by preserving the higher evidence and investigating the lower layer. Never convert `TaskChainError`, queue end, or process death directly into a game defeat or completion.

## Safe recovery rule

Classify before acting:

- Ordinary game outcome: continue according to the active contract; do not consume the technical retry budget.
- Verified recoverable UI interruption: clear it through the project ADB/screenshot path, confirm the page changed, then resume without consuming the technical retry budget.
- Technical failure: diagnose and use the current project's bounded recovery, retry budget, cooldown and deadline. Do not invent a universal retry count or waiting period. Do not repeat an unchanged failed action. After a verified local repair, reconcile existing effects and resume the same authorized remainder through its original owner; preserve a resumable save and do not replay completed daily work.
- Unknown state: preserve a current frame and pause only actions that depend on it. Route the unresolved page to AI through the existing execution channel, continue independent authorized work, and resume after repair. Do not invent clicks, mark an outbox as delivered, or wait for the user when the task already covers the remaining decision.

Never silently change gameplay theme, task type, stage, difficulty, team, resource use, retry cap, or stop condition. A home-appearance compatibility repair is not a roguelike-theme change: inspect failed templates and supported MAA routes first, preserve the user's appearance choice where feasible, and disclose any necessary temporary change.

## Finish

Report what was actually completed, failed, deferred, and still running. Include decisive evidence, cleanup state, and the next recoverable checkpoint. Update `.project-reasoning/STATE.md`; record a lesson only when the root cause is proven.
