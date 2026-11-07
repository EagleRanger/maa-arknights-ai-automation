# Integrated Strategies rewards and permanent growth

Treat each theme's reward track, permanent-growth tree, recollection/monthly mode, and investigation mode as separate objectives. Do not infer that one is complete because another is maxed.

Separate callable modules do not mean competing goals. Earning points is the
upstream of claiming their rewards. The normal composed path remains earning
experience/points -> natural settlement -> claim point-track rewards -> spend
available permanent-growth points -> return to the theme. A request to repair
only claiming can call that module without starting a new exploration. For
Reclamation Algorithm, earning prosperity points and claiming 繁荣馈赠 follow
the same distinction; a reward-only call must not reset an existing save.

The project implementation exposes `roguelike.inspect`, `roguelike.rewards`,
`roguelike.growth`, and `reclamation.rewards` through its existing prepared
session. `roguelike_progress_adapter_v1` composes these with the parent's
exploration/settlement callbacks; child modules never own whole-day execution
or application cleanup. Missing adapters return the current page to the same
execution AI, not to a second controller. Recipients without these runtime
modules should reuse the protocol, not claim that documentation installed them.

Use the same recognition consumer for live observations and offline fixtures.
Preserve raw screenshots; label simulated pending states as offline tests.
Already-complete live pages prove completion/no-op navigation, not a new claim
or upgrade. Missing OCR digits are unknown, not zero: retry a known counter ROI
at larger scale, then read its isolated line before asking the AI to inspect.
Decorative titles and pinyin can use verified page structure and local anchors.

For the shared adapter and optional repeated-failure research hook, see
[roguelike-mode-and-extension.md](roguelike-mode-and-extension.md). Theme page
differences belong in adapters; account completion facts and strategy proposals
must not be bundled as somebody else's defaults.

## Opening and bounded-floor evidence

A configured core operator is a request, not proof of recruitment. Check the
current difficulty's recruitment cost, available Hope, and actual recruited
roster. An explicit "cannot find" followed by a fallback must not be reported
as the requested core lineup; investigate the relevant grey-card, filter or
list-navigation evidence before another equivalent attempt.

For a one-floor objective, a single fight or a completed MAA chain is not a
floor clear. Require the next floor's actual boundary and an owned stop before
entering its nodes. A natural failed exploration can end the Core queue
successfully while the user objective remains unfinished. Do not turn an
adapter's arbitrary retry count into a new user-authorization requirement;
apply the actual game's resources, current strategy contract and deadline.

## Shared settlement-boundary loop

1. Wait for a real exploration settlement. Do not stop MAA or enter reward pages during combat.
2. Confirm the current theme home from a fresh game screenshot/OCR.
3. Read the theme-specific reward marker. Consult this account's verified permanent-growth fact before reopening the tree; see [account-progress.md](account-progress.md). A valid complete fact skips tree servicing, not rewards or exploration.
4. Enter only the verified named page. Require its page markers before clicking nodes or claiming rewards.
5. For a permanent-growth node, require an explicit upgrade/confirm control and prove the currency decreased or the completion marker appeared.
6. For a reward track, require the claim marker to clear or the claimed state to change.
7. Return to the same theme home and verify it before resuming the unchanged MAA contract.
8. If any confirmation is missing, preserve screenshots, record a warning, return safely when possible, and continue or pause exactly as the active contract states. Do not convert reward-service uncertainty into a battle defeat.

## Theme mapping

| Theme | Reward track | Permanent-growth tree | Growth currency | Complete marker |
| --- | --- | --- | --- | --- |
| Phantom | 古堡笔记 | 幕后筹备 | 晦暗的灵感 | Current preparation page/home shows 准备就绪 |
| Mizuki | 生态谱系 | 认知塑造 | 主观想象 | 认知完备 |
| Sami | 科考记录 | 文化比较 | 理性视阈 | Matching full counter and 研究完成 for the known tree revision |
| Sarkaz | 假说辑录 | 历史重构 | 散佚迷思 | Current matching full progress; 2026-11 adapter revision has 78 nodes |
| JieGarden | 游园纪念 | 学识古今 | 失落智识 | Current matching full progress; adapter revision has 71 nodes |
| BlackFlow | 源流堆栈 | 生命游戏 | 演化算子 | Current matching full progress; adapter revision has 67 nodes |

New-theme zero-point/entry/return observations do not establish a successful
upgrade. Preserve `needs_ai` for an unadapted positive-balance node rather than
guessing the click or claiming that no node is available. Total counts are
adapter revisions, not universal account defaults.

### Reclamation Algorithm rewards

`繁荣馈赠` is a prosperity-point exchange page, not the same UI as roguelike
level rewards. Bind item cost, remaining stock, point balance, confirmation and
post-exchange evidence separately. A sold-out page at zero points verifies a
no-op, not a new exchange. Do not copy a roguelike `一键领取` test fixture and
present it as a tested Reclamation exchange. When this account cannot expose
an available item, preserve the positive-exchange branch as Beta/AI-assisted;
do not start farming or delete a save just to manufacture that test state.

### Mizuki-specific rules

- `生态谱系` is the level reward track. It is not the permanent skill tree.
- `认知塑造` consumes `主观想象` and provides permanent bonuses in every Mizuki mode.
- The complete cognition tree costs 112 Subjective Imagination in total. Treat `认知完备` and the disappeared point counter as the completion evidence, not the reward-track level.
- Normal exploration keeps producing Subjective Imagination even after Ecology Pedigree reaches its maximum, until all cognition nodes can be completed. Therefore do not skip cognition service merely because the reward track is maxed.
- Exploration itself is the earning phase; nodes cannot be upgraded during an active exploration. Run the cognition service only at a verified settlement/home boundary.
- Current automation should first read the home counter, then scan the wide tree. A visual node candidate is not purchase authority: require the explicit upgrade button and verify the home counter decreases after returning.

单项与组合调用见[永久进度模块](progress-modules.md)。
