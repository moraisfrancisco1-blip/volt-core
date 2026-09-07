from __future__ import annotations

from typing import Any, Callable

from . import voltaris_client

# Offered to the Production Monitor's tool-use loop only when it is sweeping the
# "voltaris-os" system (see production_monitor.py) -- these read VoltarisOS's own real
# operational status, not synthetic Railway telemetry. `job` is accepted and ignored (all
# three calls are global, not per-service) purely so these handlers share the same
# call signature as railway_tools' handlers and can be dispatched through the same loop.


def get_voltaris_system_health(job: Any) -> dict:
    return voltaris_client.get_system_health()


def get_voltaris_production_readiness(job: Any) -> dict:
    return voltaris_client.get_production_readiness()


def get_voltaris_alerts(job: Any) -> dict:
    return voltaris_client.get_alerts()


TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "get_voltaris_system_health": get_voltaris_system_health,
    "get_voltaris_production_readiness": get_voltaris_production_readiness,
    "get_voltaris_alerts": get_voltaris_alerts,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_voltaris_system_health",
        "description": "Read VoltarisOS's own real system-health endpoint -- its self-reported operational status, not Railway telemetry.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_voltaris_production_readiness",
        "description": "Read VoltarisOS's own real production-readiness status.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_voltaris_alerts",
        "description": "Read VoltarisOS's own real active alerts, raised by the product itself (not by Volt Core's Production Monitor).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]
