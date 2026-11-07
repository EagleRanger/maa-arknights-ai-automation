"""Shared roguelike lifecycle; theme adapters retain their proven page readers.

No launcher, scheduler, game input, or policy change is hidden in this module.
"""
from dataclasses import dataclass
from typing import Callable

THEMES = ('Phantom', 'Mizuki', 'Sami', 'Sarkaz', 'JieGarden', 'BlackFlow')
MODES = {'exp': ('Exp', 0), 'monthly': ('Squad', 6), 'deep': ('Exploration', 7)}


def rewards_until_empty(service, limit=6):
    """A decreasing pending count is progress; zero plus home proves closure."""
    passes = []
    for _ in range(limit):
        row = service()
        passes.append(row)
        if row.get('ok') is not True or row.get('home_confirmed_after') is not True:
            return dict(row, ok=False, passes=passes)
        if row.get('pending_after') == 0:
            return dict(row, passes=passes)
        before, after = row.get('pending_before'), row.get('pending_after')
        if not (type(before) is int and type(after) is int and 0 <= after < before):
            return dict(row, ok=False, reason='reward_pending_not_decreasing', passes=passes)
    return dict(passes[-1], ok=False, reason='reward_claim_pass_limit', passes=passes)


@dataclass
class ThemeAdapter:
    theme: str
    home: Callable
    rewards: Callable
    growth: Callable
    explore: Callable
    settle: Callable
    modes: tuple = ('exp',)
    mode_complete: Callable | None = None

    def __post_init__(self):
        if self.theme not in THEMES or not set(self.modes) <= set(MODES):
            raise ValueError('unsupported_theme_or_mode')


class ProgressCycle:
    """One cycle only. The owner supplies deadline/retry/continuation decisions.

    `growth` owns account-specific completed-tree skips; `mode_complete` must
    verify that special mode's reward page, not merely TaskChainCompleted.
    """
    def __init__(self, adapter: ThemeAdapter):
        self.adapter = adapter

    def services(self):
        adapter = self.adapter
        home = adapter.home()
        if home.get('ok') is not True:
            return dict(ok=False, phase='home', home=home)
        rewards = rewards_until_empty(adapter.rewards)
        if rewards.get('ok') is not True and rewards.get('home_confirmed_after') is not True:
            return dict(ok=False, phase='rewards', rewards=rewards)
        growth = adapter.growth()
        return dict(ok=rewards.get('ok') is True and growth.get('ok') is True,
                    can_explore=growth.get('ok') is True or growth.get('home_confirmed_after') is True,
                    phase='growth', rewards=rewards, growth=growth)

    def once(self, mode='exp'):
        if mode not in self.adapter.modes:
            return dict(ok=False, reason='mode_not_adapted', theme=self.adapter.theme, mode=mode)
        before = self.services()
        if before.get('can_explore', before['ok']) is not True:
            return dict(ok=False, before=before)
        exploration = self.adapter.explore(mode)
        boundary = self.adapter.settle(exploration)
        if boundary.get('ok') is not True:
            return dict(ok=False, reason='safe_boundary_unverified', exploration=exploration, boundary=boundary)
        # A legitimate battle loss still services rewards/growth and can resume.
        after = self.services()
        completion = None
        if mode != 'exp' and self.adapter.mode_complete:
            completion = self.adapter.mode_complete(mode)
        return dict(ok=after['ok'], theme=self.adapter.theme, mode=mode,
                    before=before, exploration=exploration, boundary=boundary,
                    after=after, mode_completion=completion)
