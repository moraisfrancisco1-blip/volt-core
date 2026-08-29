import json

from app import monitoring


def test_parse_monitor_targets(monkeypatch):
    monkeypatch.setenv("VOLT_MONITOR_TARGETS", json.dumps([
        {
            "system_id": "daiane-oakes-admin",
            "system_name": "Daiane Oakes Admin Panel",
            "environment": "production",
            "url": "https://example.com/api/health/",
        }
    ]))
    targets = monitoring._parse_targets()
    assert len(targets) == 1
    assert targets[0].system_id == "daiane-oakes-admin"
    assert targets[0].url == "https://example.com/api/health"


def test_parse_monitor_targets_rejects_invalid_json(monkeypatch):
    monkeypatch.setenv("VOLT_MONITOR_TARGETS", "not-json")
    assert monitoring._parse_targets() == []


def test_parse_monitor_targets_rejects_non_http(monkeypatch):
    monkeypatch.setenv("VOLT_MONITOR_TARGETS", json.dumps([
        {"system_id": "bad", "url": "ftp://example.com/health"}
    ]))
    assert monitoring._parse_targets() == []
