"""Independent exploration operations. Return results; never advance or close a day."""
from ..core import Result
from ..runtime_session import blocked


def long(session, inputs, context, previous, operation):
    service = session.long_services.get(operation)
    if service is None: return blocked('长期模式只接独立已验监督器，不在每日内自动启动')
    return service(inputs, context)  # Existing deadline/preemption semantics.
