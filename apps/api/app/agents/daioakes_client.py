from __future__ import annotations

import os

from . import external_connector

# Confirmed by the Dai Oakes admin panel's own test suite (22 assertions): the field-level
# allowlist on payment-control (excluding clientName, clientEmail, sessionDate,
# sessionStartTime -- PII and scheduling data) is enforced server-side. The three Round 2
# endpoints below (bookings-summary, clients-summary, system-health) follow the identical
# allowlist discipline in their own route files -- see the SECURITY MODEL comment at the
# top of each one on the Dai Oakes side -- but do not yet have dedicated test suites the
# way payment-control does; that's a reasonable next step, not done here.
# Volt Core still applies its own independent allowlist on top of whatever comes back (see
# backoffice_agent.py's Dai Oakes sync) -- defense in depth, never trust a single layer
# with real health/financial data.
#
# RED LINE, non-negotiable: this key only ever authorizes the four GET endpoints below,
# all under /api/service/* on the Dai Oakes side. Every one of them is aggregate-only --
# no client name, email, phone, date of birth, or clinicalNotes ever crosses this boundary,
# by construction of the Dai Oakes route files, not just by convention here. /verify (under
# /api/payment-control, a different path) exists on the Dai Oakes side and actually writes
# (marks invoices paid via Stripe) despite taking no body -- it is outside this key's
# allowlist, and this module must never grow a function that calls it or any other
# non-/api/service/* Dai Oakes endpoint. external_connector.get() only exposes GET by
# construction, which is what makes "no write capability" a structural guarantee here, not
# just a convention.
_CONFIG = external_connector.ExternalConnectorConfig(
    name="dai-oakes",
    base_url=os.getenv("DAIOAKES_BASE_URL", ""),
    api_key_env_var="VOLT_CORE_SERVICE_KEY_DAIOAKES",
    api_key_header="X-Volt-Core-Key",
    api_key_scheme=None,
)


def get_payment_control() -> dict:
    return external_connector.get(_CONFIG, "/api/service/payment-control")


def get_bookings_summary() -> dict:
    """Aggregate booking/agenda counts only -- no client name, email, phone, or notes.
    See routes/service/bookings-summary.ts on the Dai Oakes side for the exact shape."""
    return external_connector.get(_CONFIG, "/api/service/bookings-summary")


def get_clients_summary() -> dict:
    """Two bare counts (totalClients, newClientsLast30Days) -- deliberately nothing else.
    See routes/service/clients-summary.ts on the Dai Oakes side; that file's own comment
    explains why even age or city breakdowns are excluded."""
    return external_connector.get(_CONFIG, "/api/service/clients-summary")


def get_system_health() -> dict:
    """Operational counts only (webhook/email/message delivery, admin-action volume,
    login rate-limit hits) -- no recipient, actor identity, or free-text field.
    See routes/service/system-health.ts on the Dai Oakes side for the exact shape."""
    return external_connector.get(_CONFIG, "/api/service/system-health")
