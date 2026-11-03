# Operator development and voucher interfaces

These are optional modules beside the existing published daily chain. Expose
their inputs, receipts and actual integration maturity; do not label a source
task, test adapter or screenshot as an automatically completed business flow.

## Operator mastery (test integration)

MAA's native `OperProgress` supports named development plans. The current project
adapter enables **explicit mastery goals** only: operator/role, skill 1–3,
target mastery 1–3, in user order. It does not automatically enable all elite,
level, ordinary skill, potential or module upgrades merely because MAA has
related functions. Consult the installed MAA version's protocol/schema.

Dispatch only the first unfinished mastery goal. A training-room-busy result
preserves the ongoing training. `Completed`/`PrerequisiteTraining` can indicate
that the next training **started**, not that its real-time duration has finished.
Verify actual mastery icons/current grade after collection. Persist completion
only with matching account, current queue identity and actual grade at target;
then advance to the next goal. On later normal logins claim/check/continue
without polling a new scheduled task. An error must not fall through and start
a lower-priority skill or replay daily work.

Preserve/restore the user's MAA configuration at idle boundaries. Keep auxiliary
queue logs separate from daily battle receipts. Return `waiting_training`,
verified completion, or a precise attention result; a wait is not a failed
battle and is not completion. Use the account store for verified permanent facts.

Prefer the existing daily **Infrast Training** observation when the trainee is
already in the room. Native callbacks report its operator, skill, training
grade, remaining timer or collected completion. A current verified processing
timer lets the goal service preserve that room and skip the extra character-page
visit. An expired timer, completed/idle room or unverified observation falls back
to the ordered goal check. Training grade while processing is not a finished
mastery level. Do not borrow an old queue or another account's observation.

MAA's `continue_training` option can continue the current skill before grade 3;
it is independent of the custom roster. Keeping/skipping roster changes does
not disable this option. Enable it only under the recipient's agreed training
policy; it is not the complete named-operator/skill-order planner. Do not assume
putting a trainee in `operatorsB` alone starts training. Reuse the existing
daily facility before adding a second independent visit.

## Module missions (test interface; inspect before selecting a job)

First read the named operator's actual module page: module identity, unlocked
state, both mission counters/conditions and current module level. Use existing
account facts only while their evidence/key remains valid. If complete, skip;
if partial, plan only the unfinished mission. Never search and run a job merely
because the user named an operator. Unknown progress is not zero.

For a needed battle, use a compatible existing MAA Copilot job and the proven
single-stage orchestration. Validate **mission-specific formation conditions**,
including own operator versus support, required deployment/skill, excluded
classes and named stage/mode. A three-star result alone does not prove a module
mission. Reopen/read the same module mission counters after battle and persist
only the observed change. Do not declare unlocking/level upgrades or spend
their materials unless that was explicitly requested.

For an explicitly requested module grade (beta), finish and verify missions
separately from unlocking. Check the named operator and equipped branch on the
operator detail page **before and after each grade**. A brief battle toast or
a mission counter alone is not a grade. Use the quote for the next grade;
if crafting is in scope, make only the deficit (including sub-recipes) and
return to the quote to verify actual stock. Submit once per grade, inspect
before retrying, and cache the proved terminal grade per account and branch.
An unreadable or different branch is not permission to spend.

The [badge reader](../scripts/operator_module_badge.py) accepts OCR rows from a
1920×1080 operator detail screenshot plus the expected character and branch.
This layout was verified at grades 1, 2 and 3 for one named module; unsupported
layouts return unknown. Save the original and account-bound evidence locally.
If the recipient wants only **unopened** modules, any verified advanced branch
at grade 1 or higher excludes that operator from this shortlist. An ORIGINAL
badge says what is equipped, not what the account owns. Check the named branch
card for a lock and its own 解锁 control; where several branches exist, exclude
the operator if another is already open. An uninspected branch stays unknown.
A read-only shortlist is not an instruction to spend materials.
The workshop shows “需加工 N” as a label, not a quantity-setting button. Set
the quantity with +/−; verify the selected number and ingredients **before**
starting. The recipe's internal left arrow returns to its parent ingredient;
the top-left navigation can instead return to the module quote.

### Choose high-use idle-play cores for training (optional)

Use the recipient's chosen guide author. Keep available, explicitly credited
idle-play jobs with an upload date inside the rolling two calendar years. Match
stage aliases, then count the latest dated version of each stage once (ID only
breaks time ties). Report fixed-roster, pair and triple frequencies across those
distinct stages and the denominator. Substitutes are not fixed members; views
and stars are not executions. These are sample frequencies, not server usage or
win rates. This is a training shortlist, not a battle selector: verify the exact
mode separately and inspect the recipient's actual skills/modules before spending.

Module management may be labelled `管理 +` beside the current ORIGINAL or
equipped module card; do not require a literal `模组` OCR word. Open the named
card and its requirement page, not the final material confirmation. A mission's
Go button can retain a previously selected risk mode. Re-read the actual target
stage and required normal/risk mode before Start. Ordinary progression's
already-three-star shortcut does not satisfy a new operator-specific mission;
return to the same module counters after this specific battle.

Difficulty switch text may name the destination, not the selected mode. Confirm
that meaning against the actual page/badges before clicking it. A successful
battle in the wrong mode leaves the mission incomplete; preserve that counter
and fix navigation instead of changing an already valid roster.

## Voucher capabilities and limits

MAA's documented mini-game/tools entry contains green/yellow voucher exchange;
normal `Mall` credit shopping does not automatically invoke these pipelines.
Installed resources must be checked against the actual invoking interface.

| Function | Verified native/source capability | Project boundary |
| --- | --- | --- |
| Green tickets | First-floor goods and second-floor headhunting/recruitment permit steps | A recipient may select all finite first-floor stock; never carry that preference into the second floor or another account |
| Yellow tickets | Standard headhunting and ten-pull purchase steps | Full remaining-bundle budget and reconciliation required before purchase |
| Red tickets | Chip-catalyst locator/purchase steps found | Beta: one named chip catalyst was tested; match the red tab, exact product, one unit and displayed cost. Confirm both voucher decrease and inventory increase. Never repeat an uncertain submission or enable recurring purchases from a single trial. |
| Token-to-ticket conversion | Not yet verified by this adapter | Inspect native entry before promising execution |
| Operator exchange | Not yet verified by this adapter | Exact named request and current price/banner stock required |

Full standard yellow-ticket permits currently cost **258 certificates for 38
pulls**, tiers 10/18/40/70/120, refreshing monthly on day 1 at 04:00 China time.
Kernel permits are a different product/budget. Validate live shop prices and
refresh evidence, especially for another server; never hard-code an operator
banner's rotation as this monthly permit period. See
[voucher shop data](https://prts.wiki/w/凭证交易所) and
[MAA tools](https://docs.maa.plus/zh-cn/manual/introduction/tools.html).

A full-bundle policy means: insufficient total **remaining** cost → save, no
partial purchase. Before any purchase reconcile account, current period,
currency, standard/kernel product and already-bought tiers. After an uncertain
or partial transaction re-read actual stock/balance and buy only the remainder;
do not restart the five tiers from a stale receipt. Verify all purchased tiers
and balance change before caching this period complete. Skip a fully verified
period until refresh; unknown balance is not zero and planning is not purchasing.

Inputs are private product/budget choices and fresh account-bound observations;
outputs distinguish saved budget, eligible plan, started purchase, uncertain
transaction and verified full completion. The current project has an offline
monthly yellow-bundle planner, **not a live-verified green/yellow purchasing flow**.
Keep those states explicit when sharing the Skill.
