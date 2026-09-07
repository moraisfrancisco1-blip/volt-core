from __future__ import annotations

import os

from . import external_connector

# Confirmed by the Dai Oakes admin panel's own test suite (22 assertions): the field-level
# allowlist (excluding clientName, clientEmail, sessionDate, sessionStartTime -- PII and
# scheduling data) is enforced server-side. Volt Core still applies its own independent
# allowlist on top of whatever comes back (see backoffice_agent.py's Dai Oakes sync) --
# defense in depth, never trust a single layer with real health/financial data.
#
# RED LINE, non-negotiable: this key only ever authorizes GET /api/service/payment-control.
# /verify exists on the Dai Oakes side and actually writes (marks invoices paid via Stripe)
# despite taking no body -- it is outside this key's allowlist, and this module must never
# grow a function that calls it or any other Dai Oakes endpoint. external_connector.get()
# only exposes GET by construction, which is what makes "no write capability" a structural
# guarantee here, not just a convention.
_CONFIG = external_connector.ExternalConnectorConfig(
    name="dai-oakes",
    base_url=os.getenv("DAIOAKES_BASE_URL", ""),
    api_key_env_var="VOLT_CORE_SERVICE_KEY_DAIOAKES",
    api_key_header="X-Volt-Core-Key",
    api_key_scheme=None,
)


def get_payment_control() -> dict:
    return external_connector.get(_CONFIG, "/api/service/payment-control")
