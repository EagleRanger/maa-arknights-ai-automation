"""Permanent progress plug-ins; lifecycle remains exclusively caller-owned."""
from ..core import Result
from ..runtime_session import blocked


def progress(session, inputs, context, previous, operation):
    from permanent_progress_modules_v1 import run, THEMES
    theme = 'Reclamation' if operation == 'reclamation.rewards' else inputs.get('theme')
    if theme not in THEMES:return blocked('请指定已适配的肉鸽主题，未自动切换')
    if operation.startswith('roguelike.') and theme == 'Reclamation':
        return blocked('生息演算领奖使用独立操作')
    action = operation.rsplit('.',1)[-1]
    row = run(session.app, theme, action, session.output / f'progress-{session.sequence}-{theme}-{action}')
    evidence = tuple(page['screenshot'] for page in row.get('pages',[]))
    ok = row.get('ok') is True and row.get('home_confirmed_after') is True
    return Result('succeeded' if ok and evidence else 'partial',
                  '独立进度模块已核验并返回主题页' if ok else '进度模块需原执行AI接回，环境保留', evidence, row)
