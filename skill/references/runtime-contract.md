# Runtime contract

## Authority order

Resolve conflicts in this order:

1. User's current explicit instruction.
2. Active long-term goals in `PROJECT_CONTRACT.json`.
3. User-approved project decisions.
4. Direct current evidence.
5. Technical rules and prior lessons.
6. Assistant inference.

Implementation choices may improve speed or reliability but may not change the requested result. "Use all sanity" is not authority to choose an arbitrary stage.

## Pre-run contract

Resolve these fields from the current user task and project handoff before controlling the real account. Reuse the existing run record; do not require a second manually prepared contract or confirmation packet:

- goal IDs and exact task type;
- target theme/event/chapter/stage and difficulty policy;
- ordered priority, including weekly Annihilation and limited events;
- resource policy for sanity, potions, support units, and retries;
- success evidence for every phase;
- failure transfer and states that require user intervention;
- hard stop and cleanup requirements;
- single control owner.

An explicit execution request includes normal preparation, local technical repairs, tests and continuation within its existing scope. A changed run ID, interpreter/path repair or selected implementation version is not by itself a change of business authority. Reconcile completed effects, preserve accumulated battle attempts/resource limits and return only the unfinished work to its owner.

Ask only for a decision not already covered: changed goals, resource use, difficulty or attempt limits, a new material side effect/cost, or an unresolved user choice. Respect pauses, deadlines and native tool permissions. A failed historical lookup is not an authorization withdrawal when the current task is clear; pause only genuinely uncertain actions.

## Component admission and fingerprint gate

Before the first real-account side effect, validate any project-provided component registry and protected-artifact fingerprint. A component may enter production only when its declared admission state permits it and its current artifact matches the reviewed fingerprint. If either check fails:

- stop before mutation and record the exact component and mismatch;
- do not replace the expected hash with the current hash as a shortcut;
- do not infer that a passing narrower recipe proves the drifted production component safe;
- use a separately reviewed versioned replacement or return the component for validation.

## Production recipe binding

Resolve the currently selected runtime and required components through the actual consumer before control begins. The binding must identify its reviewed snapshot, current authority, dependencies, fingerprints, scope and invalidation condition. A retained legacy recipe may be a protected dependency baseline, not the runtime selector. Scheduled runs, manual continuation and the execution brief must resolve the same binding; a dated special task neither selects nor expires an ordinary daily run.

A candidate may undergo its explicitly selected, authorized live validation without being called fully verified first. That does not authorize an automatic production switch because code exists, tests pass, or one narrow live path worked. Missing selection or drift requires repair, not silent fallback. Verify the real launcher in a no-game check, then verify the selected version/device/result on the next authorized run.

## Acceptance

- Stage completion requires post-battle/game-map evidence; MAA queue completion alone is insufficient.
- Perfect completion requires the validated node marker/result evidence, not one color assumption across all chapters or modes.
- Weekly Annihilation requires the weekly Orundum result, not merely one battle.
- Stamina use must report where sanity was spent and the remaining amount/evidence.
- Reward tasks require proof that the claim marker or reward changed.
- Long-running modes require a current checkpoint, correct theme/phase, live queue evidence, and deadline cleanup.
- Final daily completion requires one truthful report and closure of game, MAA, MuMu, and owned log windows, unless the user explicitly keeps a later queue running.
- Mainline continuation requires a fresh frontier discovery after each node; a completed MAA job is not proof that the next node was found or advanced.
- Roguelike reward servicing requires independent proof for reward claims and permanent-growth spending, followed by proof that the controller returned to the same theme.
- Event routing requires current event identity and availability evidence. An unsupported or unavailable route is not proof that no event exists.
- Fallback farming requires both explicit resource authority and current proof that no higher-priority event or unfinished applicable mainline scope remains.
- Inventory-driven base changes require fresh inventory, a project-approved policy result, and post-change state evidence; stale inventory produces a safe no-action or unchanged-product result.
- Security Service reports entry, cap state, and earned reward as separate claims. A verified capped state is an accepted no-action outcome; uncapped execution needs its own admitted handler.
- Decisive numbers require a labeled region plus stable repeated frames or independent corroboration. Do not substitute old logs or net-difference guesses for current values.

Accumulate phase evidence across one game day or one declared run. A later subprocess may add evidence but must not erase earlier verified completion. Report targeted repairs by their real scope.

## Live-run boundary

While a real MAA queue is active:

- do not run full regression, open a second MAA, or launch another supervisor;
- prefer read-only log/checkpoint/process inspection;
- apply source changes only when they cannot affect the loaded process, then replace the supervisor at a safe boundary;
- preserve screenshots and logs for unknown states before recovery.

For a cooperation-capable host, keep its process, lock and deadline checks alive while awaiting AI. Files/stdout are pending feedback, not proof of message delivery; a written recheck request is not proof of recovery. See [script-ai-cooperation.md](script-ai-cooperation.md). Do not hot-load repaired source into a running Python process or kill the only deadline owner to inspect the game.
