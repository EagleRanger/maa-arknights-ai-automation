# Account facts that change actions

The loop is: identify account → read facts → select work → execute improvement
→ verify game effect → persist evidence-bound facts → use them next time.

Use the bundled standard-library-only `scripts/account_progress_v1.py`.
Keep its data root in the consumer project's **private runtime data**, outside
this Skill and outside release packages. `actual_state.json` is the only mutable
fact source; do not maintain a contradictory hand-written account summary.
The CLI is read-only and prints both the fact and derived action for AI:

```text
python scripts/account_progress_v1.py --data-root <private-root> --client <verified-client/server> --uid <game-UID> --theme <theme> --capability permanent_growth --revision <known-tree-revision>
```

Bind client/server plus actual game UID from a verified account screen. A local
emulator index, nickname, computer username or another user's account is not
identity. The store hashes the identity to select its directory; it is local
scoping, not encryption. Never upload its JSON or screenshots with the Skill.

Each fact has theme, capability, revision, actual progress/total, source run,
verification time and preserved screenshot hashes. The caller must verify UI
semantics before `remember_verified`; `remember_complete` additionally requires
the observed full terminal. Do not write planned actions or an MAA queue ending
as game completion. Partial progress stays partial, unknown stays unknown.

`decision` returns `skip_permanent_complete` only for this exact account and
fact key with intact identity/completion evidence. Otherwise it returns
`inspect`; this is not a global run blocker. A compatible game adapter checks
the current safe theme home, skips the permanent tree when complete, and still
services independent rewards/exploration. New accounts start unknown; no
completion value is bundled.

Revision changes, account switches, explicit contradictory current counters,
or damaged evidence require reinspection. A missing OCR word is not positive
proof that a permanent upgrade disappeared. Record verified partial progress
or invalidate the old fact when actual counterevidence is available. Reuse
permanent facts across days; time-limited rewards need their own expiry logic.

The bundled store does **not** click, authenticate an account by itself,
recognize every theme, or grant gameplay/resource permission. Test the final
consumer branch: verified complete must avoid the old tree-entry function;
after a successful uncached verification, the next call must actually skip it.

Adapter pattern (the UI callbacks are supplied by the consumer, not invented
by the store):

```python
store = AccountProgress(private_data_root, verified_account_identity)
key = dict(theme=current_theme, capability="permanent_growth", revision=tree_revision)
decision = store.decision(**key)
if decision["action"] == "skip_permanent_complete" and verified_safe_theme_home:
    return skipped_tree_receipt  # independent reward service still runs
result = original_growth_service()
if result_has_verified_game_effect_and_return_home:
    store.remember_verified(**key, progress=actual_progress, total=actual_total,
        terminal_verified=actual_full_terminal, run_id=current_run_id,
        evidence=actual_effect_images, identity_evidence=account_identity_images)
```

For Sami, the consumer verifies `文化比较`, a full counter for its known tree
revision and `研究完成`; it recognizes that points may be replaced by that
terminal label. Do not invent a zero points value. In later calls the matching
safe theme home's `研究完成` can confirm the stored completion without opening
the wide tree again.
