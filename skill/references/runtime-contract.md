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

Write or log these fields before controlling the real account:

- goal IDs and exact task type;
- target theme/event/chapter/stage and difficulty policy;
- ordered priority, including weekly Annihilation and limited events;
- resource policy for sanity, potions, support units, and retries;
- success evidence for every phase;
- failure transfer and states that require user intervention;
- hard stop and cleanup requirements;
- single control owner.

If any proposal changes these fields, request user confirmation first.

## Acceptance

- Stage completion requires post-battle/game-map evidence; MAA queue completion alone is insufficient.
- Perfect completion requires the validated node marker/result evidence, not one color assumption across all chapters or modes.
- Weekly Annihilation requires the weekly Orundum result, not merely one battle.
- Stamina use must report where sanity was spent and the remaining amount/evidence.
- Reward tasks require proof that the claim marker or reward changed.
- Long-running modes require a current checkpoint, correct theme/phase, live queue evidence, and deadline cleanup.
- Final daily completion requires one truthful report and closure of game, MAA, MuMu, and owned log windows, unless the user explicitly keeps a later queue running.

## Live-run boundary

While a real MAA queue is active:

- do not run full regression, open a second MAA, or launch another supervisor;
- prefer read-only log/checkpoint/process inspection;
- apply source changes only when they cannot affect the loaded process, then replace the supervisor at a safe boundary;
- preserve screenshots and logs for unknown states before recovery.
