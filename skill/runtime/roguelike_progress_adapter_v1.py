"""Compose earning -> settlement -> rewards -> growth, without mixing scopes.

The caller supplies its existing exploration and settlement functions. Asking
for one reward module does not call them. Using ProgressCycle does, explicitly.
"""
from itertools import count
from pathlib import Path
from permanent_progress_modules_v1 import run, THEMES
from roguelike_mode_v1 import ThemeAdapter


def adapter(app, theme, output, *, explore, settle, modes=('exp',), mode_complete=None):
    if theme not in THEMES or theme == 'Reclamation':raise ValueError('roguelike theme required')
    sequence=count(1);root=Path(output)
    def call(action):
        row=run(app,theme,action,root/f'{next(sequence):03d}-{action}')
        # Keep effect and return-navigation distinct, but stop dependent
        # exploration if the previous service has not returned safely.
        return dict(row,ok=row.get('ok') is True and row.get('home_confirmed_after') is True)
    return ThemeAdapter(theme,lambda:call('inspect'),lambda:call('rewards'),
                        lambda:call('growth'),explore,settle,modes,mode_complete)
