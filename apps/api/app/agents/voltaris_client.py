from __future__ import annotations

import os

from . import external_connector

# Confirmed live against https://voltarisos-production.up.railway.app: all four paths
# below exist and return real 200 data with the correct auth. IMPORTANT, confirmed
# 2026-09-07: VoltarisOS's real API does NOT use "Authorization: Bearer <key>" -- that
# path returns 401 "Token inválido ou expirado" (it's VoltarisOS's normal end-user JWT
# auth, a completely different mechanism). The service-key path is a custom header
# instead: "X-Volt-Core-Key: <key>", raw value, no scheme prefix. Verified directly
# against all four endpoints with a real key before writing this.
#
# RED LINE, non-negotiable: VOLTARIS_SERVICE_KEY only ever authorizes read endpoints on the
# VoltarisOS side. This module must never grow a function that builds a request to a write
# endpoint (dispatch, bid, trade, toggle, or any other mutation) -- external_connector.get()
# only exposes GET by construction, which is what makes that a structural guarantee here,
# not just a convention.
_CONFIG = external_connector.ExternalConnectorConfig(
    name="voltaris-os",
    base_url=os.getenv("VOLTARIS_BASE_URL", "https://voltarisos-production.up.railway.app"),
    api_key_env_var="VOLTARIS_SERVICE_KEY",
    api_key_header="X-Volt-Core-Key",
    api_key_scheme=None,
)


def get_system_health() -> dict:
    return external_connector.get(_CONFIG, "/api/admin/system-health")


def get_production_readiness() -> dict:
    return external_connector.get(_CONFIG, "/api/admin/production-readiness")


def get_alerts() -> dict:
    return external_connector.get(_CONFIG, "/api/alerts")


def get_tenants() -> dict:
    return external_connector.get(_CONFIG, "/api/admin/tenants")
