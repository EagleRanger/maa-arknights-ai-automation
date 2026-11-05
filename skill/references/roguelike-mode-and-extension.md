# Shared roguelike mode and research extension

Use one lifecycle across themes: same-theme home → claim available rewards →
permanent growth → selected exploration mode → natural settlement → rewards /
growth → continuation. Keep theme-specific page readers and proven navigation;
do not rewrite successful UI loops to share their coordinates.

The runtime source exposes `roguelike_mode_v1.ThemeAdapter` and `ProgressCycle`.
Adapters supply `home`, `rewards`, `growth`, `explore`, `settle`, optional
`mode_complete`, and their actually supported modes. MAA IDs are exp=0,
monthly=6, deep=7. Unsupported modes return `mode_not_adapted`; never silently
substitute EXP. A completed Core chain does not prove every monthly/recollection
or investigation reward is complete. Current account evidence decides which
services can be skipped. See [roguelike-rewards.md](roguelike-rewards.md) and
[account-progress.md](account-progress.md).

The caller retains the existing deadline, retry policy, one controller, and
explicit cleanup. This interface is not a new scheduler or a second daily loop.
The first integrated consumer is Sami V7. Protocol tests cover five theme names
and three modes; they do not claim all five theme UIs were newly live-tested.

## Repeated failures and screenshots

Install `roguelike_battle_watch_v1.boundary(app, root=..., output=..., run_id=...)`
at the owning host's final Core call. It reads that PID's fresh timestamped Core
log after TaskChainStart. Do not feed it an unrelated GUI log or bare callback
strings that its parser does not support.

History is private and separated by account, theme, mode, actual difficulty and
stage. Three terminal failures in the same bucket, or at least three appearances
with survival below 50%, flag a stage. On a later appearance, capture immediately
and at 30-second intervals, at most six frames per appearance. Capture is ADB
screencap only; no new Core controller, taps, queue stops or focus changes.
Technical errors and unlocated saved settlements are not battle failures.

Preserve deployment order, operators, position, facing, cost waits, kills and
settlement plus a few hashed images. An observer failure is a warning, not a
reason to stop EXP. Reviews use the original feedback outbox and are nonblocking;
an outbox file is not proof of delivery to AI. Do not ship account ledgers or
private screenshots with the shared Skill.

## Extension for the recipient or their AI

Pass an optional Python callable as `proposal_hook` to the boundary. It receives
a data dictionary after Core returns, not during a battle. Schema:

```text
schema: roguelike-battle-review-v1
theme, difficulty_bucket, stage, account_key
baseline_sha256, current_maa_parameters
statistics, captures, evidence
```

Return the same identity/baseline fields plus `changes` (list), `rationale`,
`validation_plan`, `rollback`. `proposal_check(proposal, evidence)` validates
the data and stores it as `review_required`, always `applied=false`.
The baseline digest covers parameters, not every MAA/job resource. Before
trying a modification, the recipient's AI must also identify the current job
and resource revision. The interface never executes a returned command or
hot-edits a battle.

A user interested in optimization can ask their own AI to read the review,
propose a small local job/adapter change, preserve the previous job and validate
it in a later natural exploration. Keep this separate from normal EXP/reward /
growth automation. Public defaults do not enable autonomous strategy changes or
overwrite the recipient's adjustments. Newly wired adapters should be tested
against their real page layouts before being described as live-verified.
