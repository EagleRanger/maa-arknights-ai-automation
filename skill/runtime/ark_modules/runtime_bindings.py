"""Compatibility facade; domain modules own business, not this dispatcher."""
from .operations import select
from .runtime_session import RuntimeSession, blocked


class PreparedRuntimePort(RuntimeSession):
    def __init__(self, *args, bindings=None, operations=None, **kwargs):
        super().__init__(*args, **kwargs)
        rows = select(operations)
        self._specs = {row.name: row for row in rows}
        self._handlers = ({row.name: row.bind() for row in rows} if bindings is None else dict(bindings))
        if set(self._handlers) != set(self._specs):
            raise ValueError('operation bindings do not match the requested composition')

    def execute(self, operation, inputs, context, previous):
        if operation not in self._handlers:
            return blocked('本次任务未装配该业务模块', operation=operation)
        return self.invoke(self._specs[operation], self._handlers[operation], inputs, context, previous)

    # Old imports stay usable; aliases use the same scoped dispatch, not a
    # second business implementation or a bypass around module isolation.
    def daily(self, inputs, context, previous, operation='daily.final'):
        return self.execute(operation, inputs, context, previous)

    def mainline(self, inputs, context, previous, operation='mainline.stage'):
        return self.execute(operation, inputs, context, previous)

    def resource(self, inputs, context, previous, operation='resource.farm'):
        return self.execute(operation, inputs, context, previous)

    @staticmethod
    def base_config_current(row):
        from .domains.base import base_config_current
        return base_config_current(row)
