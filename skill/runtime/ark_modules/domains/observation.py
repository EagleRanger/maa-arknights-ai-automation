"""Independent observation operations. Return results; never advance or close a day."""
from ..core import Result
from ..runtime_session import blocked


def observe(session, inputs, context, previous, operation):
    from ..vision import Vision, RuntimeVisionPort, classify_existing
    port = RuntimeVisionPort(session.app, lambda: session.owns_control(context.owner))
    frame, paths = Vision(port, classify_existing).read('module_observe')
    return Result('succeeded' if frame.kind != 'unknown' else 'partial', '只读当前页', paths, {'page': frame.kind})
