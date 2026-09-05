# Recognition and adaptive service gates

Use this reference for page recognition, target discovery, action verification, current-event routing, inventory-driven base production, Security Service checks, and any numeric state that controls a real-account action.

## Six-layer recognition pipeline

Keep recognition and business authority separate:

1. **Scene classifier:** identify the current page from at least two independent anchors.
2. **Region extractor:** crop stable regions for the identified scene.
3. **Candidate detector:** generate possible targets from text, icon, glow, border, and layout evidence.
4. **Action gate:** require verified page, exact target, current authority, resource boundary, and controller ownership.
5. **Effect verifier:** compare before and after state; a click or task return is not success.
6. **Evidence recorder:** retain the smallest run-scoped screenshot, OCR, log window, state change, and next legal action.

Use explicit states such as `unknown`, `page_candidate`, `page_verified`, `target_candidate`, `target_verified`, `executing`, `settlement_candidate`, `completed_verified`, and `partial_or_blocked`. Only new evidence may advance the state.

## Recognition rules

- Confirm a page with at least two independent anchors from layout, text, graphic structure, and control state.
- Treat shortcut cards, recent-position cards, isolated text, one color, one pixel, and historical coordinates as candidate evidence only.
- Run OCR on stable labeled regions. Preserve raw text, normalized text, region, frame time, and recognition version when the value affects an action.
- Require stable repeated frames or independent corroboration for stamina, reward counters, inventory, cap values, and other decisive numbers.
- If an action produces no explainable page, control, marker, or numeric change, reclassify the scene and stop after bounded rechecks. Do not increase blind clicks.
- Scope MAA logs to the current run and session. A rotated or older log may support same-run history only when its run boundary is proved.

## Current-event and fallback routing

An event being unavailable for automated execution is not evidence that no event exists.

1. Inspect the current terminal/event surface from a fresh frame.
2. Confirm event identity and available stage family before selecting a job.
3. Distinguish: no current event; current event with compatible verified job; event with no compatible job; event discovery or network failure; unknown navigation.
4. Preserve unfinished event scope when no compatible job exists. Follow only the pre-approved transfer, such as mainline verification.
5. Use a fallback farm only when the contract authorizes it and current evidence shows no higher-priority event or unfinished applicable mainline scope.
6. A validation-only adapter or candidate workflow cannot become the daily production route until its real forward path and containment pass independently.

## Inventory-driven base production

The public Skill does not prescribe one base layout or product mix. The receiving project supplies an approved policy that maps fresh inventory to a bounded production plan.

- Read current inventory in the same run before selecting the plan.
- Validate that the chosen plan belongs to the approved policy set.
- Apply product, staffing, and replenishment changes through verified controls.
- Prove the resulting base state rather than only the configuration command.
- If inventory is stale, ambiguous, or unavailable, preserve the current product state and report the decision as unverified or no-action.
- Never convert one author's resource thresholds into a universal default.

## Security Service cap-state gate

Treat entry, cycle completion, and reward-cap state as separate claims.

1. Enter through a verified stable navigation path, not a visually similar shortcut.
2. Identify the current service page and cycle.
3. Read each relevant reward-cap dimension from a stable labeled region.
4. When all required dimensions are capped, record a verified no-action short circuit.
5. When uncapped, run only a separately validated production handler with its own target, evidence, resource, and stop contract.
6. Returning to the page or starting MAA does not prove rewards were earned.

A capped short circuit can be production-accepted even when the uncapped earning path is still unverified; keep those scopes explicit.

## Acceptance and candidate isolation

For every adaptive service, report independently:

- page and target identity;
- action ownership and approved recipe identity;
- observed effect;
- numeric or marker change;
- current-run evidence scope;
- final result: verified, partial, blocked, or unverified;
- cleanup and next legal action.

Keep accepted production and candidate validation under different immutable identities. Never refresh a protected fingerprint, rewrite an accepted component in place, or switch a production pointer merely because offline tests pass.
