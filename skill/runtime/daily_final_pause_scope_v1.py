"""Battle pause must not suppress an actually completed daily tail's inspection."""
import ast
from pathlib import Path
from contextlib import contextmanager

OLD='mode in ("daily", "full", "event_today") and not flow_paused'
NEW='mode in ("daily", "full", "event_today") and (not flow_paused or (_RUN_SUMMARY.get("final_daily_requested") is True and _RUN_SUMMARY.get("final_daily_completed") is True and _confirm_daily_chains_complete()))'


def adapted_main(source):
    tree=ast.parse(source)
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    matches=[n for n in ast.walk(fn) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='daily_tail_expected' for t in n.targets)]
    if len(matches)!=1 or ast.dump(matches[0].value)!=ast.dump(ast.parse(OLD,mode='eval').body):
        raise ValueError('final daily boundary source changed')
    matches[0].value=ast.parse(NEW,mode='eval').body
    return ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))


@contextmanager
def boundary(app):
    old=app.main
    # Compile only the existing function definition, not module top-level code.
    tree=adapted_main(Path(app.__file__).read_text(encoding='utf-8-sig'))
    namespace={}
    exec(compile(tree,'<daily-final-pause-scope-v1>','exec'),app.__dict__,namespace)
    app.main=namespace['main']
    try:yield
    finally:app.main=old
