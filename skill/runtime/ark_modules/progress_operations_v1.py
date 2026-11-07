"""Progress-only extension to the frozen daily catalogue.

Uses the same RuntimeSession and core Module/Dispatcher contract, without
changing the frozen daily/base plan compiler or making these daily defaults.
"""
from .core import Module
from .operations import Operation
from .runtime_session import RuntimeSession, blocked

CATALOGUE = tuple(Operation(name, 'progress', 'progress', ('ocr','tap','swipe')) for name in (
    'roguelike.inspect','roguelike.rewards','roguelike.growth','reclamation.rewards'))
BY_NAME = {row.name:row for row in CATALOGUE}


class ProgressRuntimePort(RuntimeSession):
    def execute(self, operation, inputs, context, previous=None):
        spec=BY_NAME.get(operation)
        if spec is None:return blocked('此接口仅处理肉鸽永久进度和生息演算领奖')
        return self.invoke(spec,spec.bind(),inputs,context,previous or {})

    def modules(self, context):
        return {name:Module(lambda inputs, name=name:self.execute(name,inputs,context))
                for name in BY_NAME}
