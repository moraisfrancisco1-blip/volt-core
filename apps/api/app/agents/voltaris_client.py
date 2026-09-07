from __future__ import annotations

import os

from . import external_connector

# Confirmed live 2026-09-07 against https://voltarisos-production.up.railway.app: all four
# paths below exist and require Bearer auth ("Token inválido ou expirado" once a token is
# sent, vs "Autenticação necessária" with none) -- the shape here is real, not guessed.
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
)


def get_system_health() -> dict:
    return external_connector.get(_CONFIG, "/api/admin/system-health")


def get_production_readiness() -> dict:
    return external_connector.get(_CONFIG, "/api/admin/production-readiness")


def get_alerts() -> dict:
    return external_connector.get(_CONFIG, "/api/alerts")


def get_tenants() -> dict:
    return external_connector.get(_CONFIG, "/api/admin/tenants")
