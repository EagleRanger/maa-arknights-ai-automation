# Recognition, effects and report scopes

Use this reference when a screenshot, MAA callback or report disagrees. These
are diagnostic methods, not extra permission gates or a reason to replay a
completed daily run.

## Attribute the failure to its producer

Trace the saved frame through the actual callable: capture → page/ROI → OCR
raw text → bounded normalization → scene/effect predicate → ledger → report.
Repair the first disproven layer. A readable raw label rejected by an exact
comparison is not evidence that the OCR installation is stale; a correct
number attached to the wrong phase is an accounting error.

MAA's internal OCR and the Python controller's OCR are independent. Verify
the loaded interpreter/library, detector and recognizer weights, configuration
and call path separately. Library versions, MAA versions and model generations
are different identifiers. If a recognizer's metadata gives only training
statistics, report its generation as unknown; do not label the whole stack
from its detector or an old conversation.

Before changing a model, replay the actual blocking frames under the same ROI
and decision rule. Report successful workflow decisions and latency, not only
generic character accuracy. A small saved sample does not prove universal
accuracy. Reuse a current accepted model when a local parser repair is enough.

## Bound normalization and page identity

Keep raw text alongside normalized text. Compatibility is field- and
layout-specific: an observed accent artifact in a complete status word may
be normalized for that status, but must not alter costs, counters, Chinese
button names or click targets globally. Preserve near-match rejection tests.

Require only observations that establish the decision at hand. Do not make
unrelated low-contrast text (for example health when confirming an unplayed
first-floor route) a mandatory identity check. Use multiple relevant page
anchors and the saved counterexample; keep resource or health checks only
where the next action actually depends on those values.

Distinguish absent OCR from contradictory evidence. In a known layout, an
exact unique stage title plus independent page/action anchors can establish
identity when a redundant Latin stage code is omitted. An explicit different
code or title must still reject the action. Prove this alternative against
the actual failed frame and negative cases; do not silently assign a guessed
code. Resume the already-prepared page through its owner rather than repeat
login, squad setup or completed work merely to obtain the missing text.

Validate capture before blaming recognition: a screenshot command returning
help text, a missing file or a decode error is not a black game frame. Inspect
the saved image/signature, exact device and capture result. Another verified
view may disprove a game freeze, but it does not replace the fresh control-side
frame required for the next input. Repair only the failed capture call and
reconcile prior side effects before retrying any action.

Specific page identities take precedence over generic shared words. Result
briefs can contain battle words; a saved-record selection can contain squad
words. Isolate each card/row's timestamp, count, selection border and action.
Do not borrow a missing zero from another card. Prefer an existing MAA
template for an already-supported control over a new unverified macro.

## Separate effects and resource observation periods

An observed balance is not a battle-cost ledger. Keep the earliest verified
run-start observation, subsequent segment starts and final observation as
distinct records. A second segment still takes a fresh reading for its own
resource decision, but must not overwrite the whole-run origin. A new run
must not inherit an old start or use planned costs as actual effects.

The accounting window and balance interval must cover the same effects.
Reconcile actual per-session settlements, batch quantities and refunds;
weekly proxy battles and resource farming may be separate phases in one run.
Show residual balance changes as unexplained unless their source is directly
proved. Nonzero balance below the chosen stage cost is not zero and need not
mean stamina use failed.

## Validate composition and correct reports without replay

Test the saved counterexample and relevant negatives, then execute the real
installer graph with game/process/network leaves isolated. Check behavior at
the final call site and required cleanup/report exit points; an imported name
or installed flag does not prove the effective function was used.

For a standalone game host, validate both the configured emulator identity
and the portable MAA executable/configuration/resource binding. Shared
preparation alone need not bind the emulator; binding the emulator alone need
not prepare MAA. Reuse the complete verified entry and keep identity binding
active through startup, navigation, Core work and cleanup. Exercise those
phases at the real host call seam, including an initially stopped target and
a stale address for another instance. A no-battle preparation failure does
not consume an exploration attempt or authorize replaying completed daily work.

For task-resource overlays, preserving candidate strings is not sufficient:
preserve the definition layer and inherited namespace resolution as well.
Do not flatten a generic template into a named theme task with unqualified
children. Insert a local stop condition without deleting fallback routes for
automatic transition screens. Resource loading and task append validate syntax,
not live routing; keep the counterexample and check the actual task names.

Supervision must use the active run's time and controller identity. If callback
files are flushed only on exit, the newest file can still belong to a previous
run. Use its live log or terminal instead; never declare the current task stopped
from that older file. A repeated no-progress action on a verified noncombat page
is a technical fault, not a failed battle or authority to abandon the save.

Keep first clear, saved proxy record, milestone claims, weekly cap, remaining
sanity and post-battle daily collection as separate effects. Copilot battles
also advance the last-battle boundary: an older Award queue cannot prove new
post-battle rewards were collected. Claim clicks alone are not reward proof;
verify the same reward marker or counter after the action.

When only verification/reporting is wrong, bind a derived correction to the
exact sealed run, source hashes and saved evidence. Preserve originals and
business/cleanup status. Recheck JSON, totals and detail text together. Do not
restart the game, repeat a claim/battle/base change, or show another completion
popup just to make a corrected record. Store permanent regression fixtures
outside disposable runtime screenshot directories.
