from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import httpx

_API_BASE = "https://web-api.tp.entsoe.eu/api"
# Day-ahead prices document type, NL bidding zone (EIC code) -- both fixed by what this
# function reports on, not configurable per call.
_DOCUMENT_TYPE = "A44"
_NL_DOMAIN = "10YNL----------L"
_NS = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}


def _entsoe_request(params: dict) -> httpx.Response | None:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    # Returns None only on a transport-level failure; non-2xx statuses (e.g. an invalid
    # or missing token) come back as a normal Response for the caller to interpret.
    token = os.getenv("ENTSOE_API_TOKEN")
    if not token:
        return None
    try:
        with httpx.Client(base_url=_API_BASE, timeout=15) as client:
            return client.get("", params={**params, "securityToken": token})
    except httpx.HTTPError:
        return None


def fetch_entsoe_day_ahead_prices(days: int = 7) -> dict:
    # Returns {"prices": [{"start": iso, "price_eur_mwh": float}, ...]} on success, or
    # {"error": "..."} -- never raises, matching every other agent tool's contract so a
    # missing token or a transient ENTSO-E outage degrades the weekly report instead of
    # aborting it.
    if not os.getenv("ENTSOE_API_TOKEN"):
        return {"error": "ENTSOE_API_TOKEN not configured"}

    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(days=days)
    params = {
        "documentType": _DOCUMENT_TYPE,
        "in_Domain": _NL_DOMAIN,
        "out_Domain": _NL_DOMAIN,
        "periodStart": period_start.strftime("%Y%m%d%H%M"),
        "periodEnd": period_end.strftime("%Y%m%d%H%M"),
    }
    response = _entsoe_request(params)
    if response is None:
        return {"error": "network/transport error contacting ENTSO-E"}
    if response.status_code != 200:
        return {"error": f"ENTSO-E API error {response.status_code}: {response.text[:500]}"}

    try:
        return {"prices": _parse_day_ahead_prices(response.text)}
    except ElementTree.ParseError as exc:
        return {"error": f"could not parse ENTSO-E response: {exc}"}


def _parse_day_ahead_prices(xml_text: str) -> list[dict]:
    root = ElementTree.fromstring(xml_text)
    prices: list[dict] = []
    for period in root.iterfind(".//ns:Period", _NS):
        start_el = period.find("./ns:timeInterval/ns:start", _NS)
        resolution_el = period.find("./ns:resolution", _NS)
        if start_el is None or start_el.text is None or resolution_el is None or resolution_el.text is None:
            continue
        period_start = datetime.strptime(start_el.text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
        step = _resolution_to_timedelta(resolution_el.text)
        for point in period.iterfind("./ns:Point", _NS):
            position_el = point.find("./ns:position", _NS)
            price_el = point.find("./ns:price.amount", _NS)
            if position_el is None or position_el.text is None or price_el is None or price_el.text is None:
                continue
            position = int(position_el.text)
            point_start = period_start + step * (position - 1)
            prices.append({"start": point_start.isoformat(), "price_eur_mwh": float(price_el.text)})
    return prices


def _resolution_to_timedelta(resolution: str) -> timedelta:
    # ENTSO-E resolutions are ISO 8601 durations; day-ahead prices only ever use PT15M,
    # PT30M or PT60M in practice -- handling exactly those three keeps this parser honest
    # about what it actually supports instead of pulling in a full ISO 8601 library.
    mapping = {"PT15M": timedelta(minutes=15), "PT30M": timedelta(minutes=30), "PT60M": timedelta(hours=1)}
    if resolution not in mapping:
        raise ElementTree.ParseError(f"unsupported ENTSO-E resolution {resolution!r}")
    return mapping[resolution]
