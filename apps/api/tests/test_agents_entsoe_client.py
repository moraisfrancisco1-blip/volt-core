from types import SimpleNamespace

from app.agents import entsoe_client

_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <TimeSeries>
    <Period>
      <timeInterval>
        <start>2026-09-01T00:00Z</start>
        <end>2026-09-01T02:00Z</end>
      </timeInterval>
      <resolution>PT60M</resolution>
      <Point>
        <position>1</position>
        <price.amount>45.50</price.amount>
      </Point>
      <Point>
        <position>2</position>
        <price.amount>50.25</price.amount>
      </Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>"""


def _fake_response(status_code=200, text=""):
    return SimpleNamespace(status_code=status_code, text=text)


def test_fetch_day_ahead_prices_without_token_returns_error(monkeypatch):
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    result = entsoe_client.fetch_entsoe_day_ahead_prices()
    assert result == {"error": "ENTSOE_API_TOKEN not configured"}


def test_fetch_day_ahead_prices_success_parses_points(monkeypatch):
    monkeypatch.setenv("ENTSOE_API_TOKEN", "fake-token")
    monkeypatch.setattr(entsoe_client, "_entsoe_request", lambda params: _fake_response(200, _SAMPLE_XML))

    result = entsoe_client.fetch_entsoe_day_ahead_prices()

    assert "error" not in result
    prices = result["prices"]
    assert len(prices) == 2
    assert prices[0] == {"start": "2026-09-01T00:00:00+00:00", "price_eur_mwh": 45.5}
    assert prices[1] == {"start": "2026-09-01T01:00:00+00:00", "price_eur_mwh": 50.25}


def test_fetch_day_ahead_prices_reports_non_200(monkeypatch):
    monkeypatch.setenv("ENTSOE_API_TOKEN", "fake-token")
    monkeypatch.setattr(entsoe_client, "_entsoe_request", lambda params: _fake_response(401, "invalid security token"))

    result = entsoe_client.fetch_entsoe_day_ahead_prices()

    assert "error" in result
    assert "401" in result["error"]


def test_fetch_day_ahead_prices_reports_transport_failure(monkeypatch):
    monkeypatch.setenv("ENTSOE_API_TOKEN", "fake-token")
    monkeypatch.setattr(entsoe_client, "_entsoe_request", lambda params: None)

    result = entsoe_client.fetch_entsoe_day_ahead_prices()

    assert "network/transport error" in result["error"]


def test_fetch_day_ahead_prices_reports_malformed_xml(monkeypatch):
    monkeypatch.setenv("ENTSOE_API_TOKEN", "fake-token")
    monkeypatch.setattr(entsoe_client, "_entsoe_request", lambda params: _fake_response(200, "not xml at all <<<"))

    result = entsoe_client.fetch_entsoe_day_ahead_prices()

    assert "error" in result
    assert "could not parse" in result["error"]


def test_entsoe_request_returns_none_without_token(monkeypatch):
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    assert entsoe_client._entsoe_request({}) is None
