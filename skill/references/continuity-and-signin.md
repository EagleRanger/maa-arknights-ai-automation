# Continuation, updates and sign-in

Use this when a daily run stops at startup, an activity page, a claim, or an AI
handoff. The user's remaining objective persists across technical run IDs.

## Continue the right remainder

- Reconcile the previous run and real controller/queue state. A preserved
  interrupted manifest can say `running` after its controller has exited; use
  the same-run reconciliation rather than invent a live process or success.
- A user-completed substep is a scoped fact. Bind it to the current account or
  device session and game day/activity period; skip only that substep. Expire or
  recheck on a new day, account or period. Do not skip battles/base/Award because
  the user completed sign-in, or credit manual work as automation.
- A partial run report is not the end of the authorized daily objective. Repair
  the cause, preserve effects, and dispatch the unchanged remainder to its
  original owner. Do not ask the user to repeat the same authorization.

## Separate updates

- A required client-package upgrade is not a network timeout. Discover the
  installed package/channel/version, use the channel's official source, preserve
  data, rely on Android signature validation, and read back the installed version.
  Never uninstall, clear account data, downgrade, or swap channels as a shortcut.
- In-game resource download, extraction and verification are progress states.
  Locate the explicit resource-download confirmation, wait while progress moves,
  and use the current host's bounded stall/deadline policy. Recheck the actual
  home after completion. A successful install is not a completed daily run.
- MAA application, task definitions/templates, game maps and activity calendars
  have separate versions. Read each relevant source. A stale calendar or missing
  navigation entry does not prove that Copilot jobs or game maps do not exist.
- Research current official resources and exact-stage jobs while independent
  daily work continues. Do not replace active-event stamina with unrelated farms
  just because route metadata is missing. Apply resource changes only when the
  relevant MAA owner is idle, preserving local overlays and rollback evidence.

For MAA application updates, finish the daily objective first: an explicit
update prompt on the initial MAA startup may be accepted before any queue;
after daily work starts, choose the prompt's actual `稍后`/`否` and finish the
remaining modules. Remember the deferred package for the next daily startup,
not the next mid-run MAA reload. A successful update is not successful gameplay.
Temporary task configuration must restore only its own changes; do not write an
old whole-file snapshot over MAA's newly migrated settings/version fields.

MAA's post-update `设置指引` is a human demo, not an AI workflow prerequisite.
Skip it through its supported skip control or a source-verified version-specific
configuration adapter. The supplied project adapter currently knows MAA
6.21.2/6.21.3; unknown guide schemas go to AI rather than guessed completion.
Re-read the real task page and require a visible, enabled Start control; do not
invoke a hidden/disabled control behind the guide. This does not skip the
recipient's own account/environment/resource setup in this Skill.

## Generic sign-in, not an activity-name macro

Recognize entry text such as `签到`/login rewards, then establish the overlay with
its date, repeated day cards, current highlight or explicit claim/received state.
An activity name or red dot is a clue, not the whole recognizer or claim proof.
Do not make one event's yellow-card skin or left-side label universal.

1. Locate the current reward card or explicit free claim control. Never infer
   permission for paid catch-up, purchases, gacha, or a reward choice.
2. After one claim, read a fresh reward/result and the same card's received
   marker or counter. A click alone does not prove a reward.
3. Keep claim effect and closure separate. A received explanation page can stay
   open after the reward. Preserve the proved claim, do not tap it again, locate
   its visible X, then read the next page. Another recognized reward overlay is
   a valid next step, not a failed claim merely because home is not visible yet.
   Drain that chain through its own handlers; verify home at the chain boundary.
4. If OCR misses X, reuse a verified visual template or graphic-shape locator
   with page and geometry evidence. OCR `X` alone is insufficient: a currency
   `+` on home can be misread as X. Validate stroke direction and contrast
   polarity against the current image; do not guess a top-right point.
5. If no reliable action is known, return `reward_pending` and a fresh frame to
   AI. A positively identified close control may return to a verified home so
   other daily work continues; unknown navigation must not be treated as home.

Record activity identity and actual announced start/end separately from the
game day of a claim. On a wish-wall overlay, zero remaining choices alone
does not prove payout; the received marker plus drawn/completed state is
stronger. On a calendar overlay, match today's card or received result; future
cards can be locked on a day that is already claimed. Close via the overlay's
own X, handle any next overlay, and verify home. Do not credit prior/manual
receipt as automatic. Already-received evidence belongs to the actual account
and game day; missing an unclaimed card does not establish a missing reward.

For the ordinary `今日配给` / `每日配给` startup overlay, the title and its
established bottom confirmation control are enough to dismiss it. Reward names
are random and must not be a whitelist for clicking the checkmark. Re-read the
page after the click. Sign-in and wish-wall activities are optional: absent or
expired activities do not become mandatory startup failures.

Keep actual announced start/end distinct from the
first observed open time. New activity instances never inherit old claimed or
expired state just because both say `签到`. Expired instances leave their template
available but are no longer daily work.

## One script/AI handoff, not two blind watchers

The script detects and captures; the execution AI first reads the fresh image
and handles an ordinary in-scope page recovery itself. It sends recurring code
defects, missing capabilities or conflicting results to the project lane. A
notification is not a requirement to wait for project approval before using an
obvious observed Back/Close/Confirm control. The original owner rechecks and
resumes the same step. User absence does not stop this already-authorized chain.
No new scheduler, mouse takeover or duplicate owner.

Use an existing supported pause/reply seam to keep a healthy environment open.
After the configured recovery budget (three rounds in the current adapter),
retain the original controller, game, MAA and emulator and send the fresh frame
to the execution AI. The AI corrects only the affected page, then the same owner
performs a fresh read-only recheck before resuming the original step. Do not
auto-close the environment just because the error has been reported. The daily
wait has no built-in timer; the owning host must honor any explicit deadline or
stop by submitting a bound stop reply through this seam. This is a startup seam,
not a claim that every MAA-internal failure already supports live recovery.
If that host lacks it, do not invent a live-wait capability: preserve an honest
partial result and continue through the verified repair entry after safe
reconciliation. A safe per-run stop does not abandon the objective.
Outbox created, native delivery accepted, project received, repair applied and
game effect verified are distinct states. A message or log alone proves none
of the later states.

### Navigation evidence is not tied to OCR agreement

Prefer the existing recognizer when it works. If the execution AI sees the
correct homepage but its typography still defeats OCR, use the navigation-only
visual reply when that runtime provides it: `tools/ark_navigation_reply_v1.py`
with the original run/event, the actual screenshot and a brief observation.
The owner compares a fresh navigation surface to that picture before accepting
it; a changed scene stays in the same wait for re-observation, not cleanup.
This grants only navigation readiness, never a reward, battle, training or
account completion. The ordinary `recheck` remains sufficient when OCR works.
An older loaded owner without this adapter keeps its current supported seam;
do not claim a source-file edit has hot-loaded into it.

For optional services, restore navigation **before returning to the enclosing
workflow**. A failed newspaper layout remains pending, but after home recovery
the enclosing activity route keeps its successful stage result and may farm.
Do not first freeze stamina, unwind into final cleanup, then call that recovery
complete merely because the homepage was restored. If an older owner already
skipped a phase, reconcile its effects and dispatch only that missing phase and
the necessary post-action cleanup through the currently selected runtime.

Use account/activity/game-day identity for a claim already verified in this run.
Reopening a horizontally shifted calendar does not invalidate the proved claim
just because its card moved. Reuse that claim proof, do not count it twice, and
do not infer today's claim from an unrelated old stamp or zero counter.

## Tutorials are a capability gap, not automatically human-only

Detailed execution, visual-step checks and human fallback are in
[tutorial-ai.md](tutorial-ai.md), released as “教学关代理逻辑（测试）”.

When the active user task permits tutorial progression, first check exact-stage
Copilot work and the game's visible instructions. No compatible Copilot result
is not proof that AI cannot complete the tutorial. At an idle control boundary,
use fresh frames to follow the highlighted clicks, deployments and facing
gestures through the existing background input path. Public shipped tutorial
scripts can clarify required signals and target tiles; reconcile them with the
actual stage, frame and map projection rather than blindly replaying coordinates.
Selecting a deployment card can tilt the camera. Capture that selected state
before locating its destination; validate selection, placement and facing as
separate transitions. Wait for the new frame sequence before the next command.
Verify each requested transition and the final game result. Hand off only the
unresolved step when no safe next action is known. Preserve successful steps and
continue independent daily work; never add a universal “TR means manual” gate.

## Validate the consumer that runs

Replay the actual missed frame and negatives. Then assert the actual handler
result after every historical installer/wrapper is active; an entry reached,
imported function or install flag can hide an overwritten handler. Test manual
scope, reward-versus-close effects, unknown-to-AI transfer, independent work and
final report/cleanup separately. Candidate tests do not count as live passes,
and user clicks never supply an automatic stability pass. Preserve readable
fixtures outside disposable screenshots; do not export account IDs or progress.
Do not replace the startup/navigation function under test with a mock that calls
the desired handler: that can hide the real branch which skipped it. Stub only
external device I/O and exercise the final composed entrypoint and transitions.
Include the real current-plan compiler in an entry test: artifact fingerprints
alone do not detect a policy/schema mismatch. Check effective resource settings
after legacy bootstrap wrappers rebuild arguments, not just the command passed
to the launcher. Keep the bootstrap's one run identity. A legacy policy label
such as `pause_and_report` can remain for compatibility while its defined scope
is local recovery and AI continuation; renaming the label is not the behavior
change, and must not create a new startup blocker.

Preserve decisive fault frames with a hash when the existing outbox is created;
record missing/copy-failed evidence honestly without blocking independent work.
Do not re-copy or rewrite an already acknowledged packet. Keep this bounded
(for example only the few frames explaining the failure), not an archive of
every screenshot. An absent historical test image is missing coverage, not a
passing regression; replacement real frames must be labelled as replacements.

## Copilot failures and upstream holds

Use exact-stage packaged Copilot work, honoring the user's configured author
and idle-play preferences within compatible candidates. Read the job's current
instructions before execution: an explicit unresolved map/deployment defect is
not a reason to spend another game attempt. A video is not a packaged job and
does not authorize writing a new battle controller.

Separate preparation retries, actual battle-budget use, observed defeats and
unverified outcomes. A budget list may contain stalled or non-perfect battles;
only count a defeat from its real result. Keep the final popup concise (stage,
unfinished state, verified failure count); detailed causes belong in the chat
and evidence. Never reset the budget just because the process resumed.

When the user elects to wait for an upstream fix, store a scoped stage/mode hold
in their existing local configuration. Do not replay it each daily run or mark
it cleared. Keep eligible independent activity farming/rewards/daily work on
their existing evidence checks; do not silently divert active-event sanity to
unrelated resources. A new version number or homepage-fix announcement does
not by itself prove that the held stage's deployment defect is fixed.
