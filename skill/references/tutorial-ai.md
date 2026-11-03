# 教学关代理逻辑（测试）

Use this title in release notes. This is AI-assisted visual tutorial handling,
not a claim that MAA has jobs for all tutorials or that all tutorials are solved.

When a known tutorial blocks the user's requested route, reuse an already
compatible exact-stage job if available. Otherwise route the current screen to
the AI conversation first. No MAA job is not a reason to immediately demand
manual play. A completed tutorial is skipped using the current account's proof.

At the existing single-owner idle boundary, the AI uses background screenshot
and input to read instructions, highlighted tiles and facing gestures:

- Identify the requested operator or device and the current instruction.
- Select the card, then capture again: selection can tilt the camera. Locate
  the target in this selected view, not the previous screenshot.
- Separate placement from facing and check costs, card/device count, the unit
  on the field or the next instruction before continuing.
- Reobserve and correct an ineffective action. Apply the host's bounded
  same-step recovery policy; do not limit a whole tutorial to three actions or
  replay an unchanged failed drag indefinitely.
- Verify the exact-stage result and the later completion marker/return route.
  Store evidence in the account's private progress record, not shared Skill
  instructions. Resume only the original remainder.

If the AI cannot finish after its actual attempt, show a plain-language manual
handoff notice naming the unresolved instruction and preserve the current
evidence. Missing jobs, a temporarily busy queue or a failed screenshot alone
do not establish that human play is necessary. Only dependent progression
waits; independent daily work remains with its original executor. Never add a
second supervisor, foreground mouse control or new resource use.

The project implementation uses `tutorial_ai_handoff_v2.py` for AI-first routing,
`tools/tutorial_session_v2.py` for named tutorial interaction, and
`tutorial_session_result_v1.py` for reviewed outcomes and the existing popup.
Integrate them with the recipient's actual runtime before claiming availability;
this reference does not itself create a controller or install those files.

The initial live case completed one zero-sanity tutorial with AI guidance.
One misplaced device was corrected after capturing the selected/tilted view.
It is evidence for this workflow, not universal tutorial coverage. Keep durable
copies of selected/result/return evidence outside rotating screenshot caches.
Technical session resumes are not new gameplay attempts or stability passes.
