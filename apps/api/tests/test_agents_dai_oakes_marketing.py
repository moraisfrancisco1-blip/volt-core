from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import dai_oakes_marketing
from app.db import session_scope
from app.models import AuditRecord, DaiOakesMarketingContentRecord


@pytest.fixture(autouse=True)
def _default_provider_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-not-real")


def _tool_response(tool_name, input_dict):
    return SimpleNamespace(
        content=[{"type": "tool_use", "name": tool_name, "input": input_dict, "id": "toolu_1"}],
        stop_reason="tool_use", input_tokens=50, output_tokens=20,
    )


def _latest_content() -> DaiOakesMarketingContentRecord | None:
    with session_scope() as session:
        row = session.scalar(select(DaiOakesMarketingContentRecord).order_by(DaiOakesMarketingContentRecord.id.desc()))
        if row is not None:
            session.expunge(row)
        return row


# --- _fetch_dai_oakes_facts -- the ONLY network call this agent makes, and only to the
# clinic's own public, unauthenticated website (no patient data anywhere on this path) ----

class _FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        if self._exc:
            raise self._exc
        return self._response


def test_fetch_facts_extracts_title_and_meta_description(monkeypatch):
    html = (
        "<html><head><title>Studio Daï Oakes</title>"
        '<meta name="description" content="Pelvic floor &amp; postpartum specialist in Rotterdam">'
        "</head></html>"
    )
    monkeypatch.setattr(dai_oakes_marketing.httpx, "Client", lambda **kw: _FakeClient(_FakeResponse(200, html)))
    facts, sources = dai_oakes_marketing._fetch_dai_oakes_facts()
    assert "Studio Daï Oakes" in facts
    assert "Pelvic floor & postpartum specialist in Rotterdam" in facts
    assert sources == ["title", "meta description"]


def test_fetch_facts_dedupes_og_tags_identical_to_title_and_description(monkeypatch):
    html = (
        "<html><head><title>Same Title</title>"
        '<meta name="description" content="Same description">'
        '<meta property="og:title" content="Same Title">'
        '<meta property="og:description" content="Same description">'
        "</head></html>"
    )
    monkeypatch.setattr(dai_oakes_marketing.httpx, "Client", lambda **kw: _FakeClient(_FakeResponse(200, html)))
    facts, sources = dai_oakes_marketing._fetch_dai_oakes_facts()
    # og:title/og:description must not duplicate identical title/meta description content.
    assert sources == ["title", "meta description"]


def test_fetch_facts_includes_og_tags_when_different(monkeypatch):
    html = (
        "<html><head><title>Site Title</title>"
        '<meta name="description" content="Site description">'
        '<meta property="og:title" content="Social Title">'
        '<meta property="og:description" content="Social description">'
        "</head></html>"
    )
    monkeypatch.setattr(dai_oakes_marketing.httpx, "Client", lambda **kw: _FakeClient(_FakeResponse(200, html)))
    facts, sources = dai_oakes_marketing._fetch_dai_oakes_facts()
    assert "Social Title" in facts
    assert "Social description" in facts
    assert sources == ["title", "meta description", "og:title", "og:description"]


def test_fetch_facts_returns_no_facts_text_on_non_200(monkeypatch):
    monkeypatch.setattr(dai_oakes_marketing.httpx, "Client", lambda **kw: _FakeClient(_FakeResponse(503, "")))
    facts, sources = dai_oakes_marketing._fetch_dai_oakes_facts()
    assert facts == dai_oakes_marketing._NO_FACTS_TEXT
    assert sources == []


def test_fetch_facts_returns_no_facts_text_on_transport_error(monkeypatch):
    import httpx as httpx_module
    monkeypatch.setattr(dai_oakes_marketing.httpx, "Client", lambda **kw: _FakeClient(exc=httpx_module.ConnectError("simulated DNS failure")))
    facts, sources = dai_oakes_marketing._fetch_dai_oakes_facts()
    assert facts == dai_oakes_marketing._NO_FACTS_TEXT
    assert sources == []


def test_fetch_facts_returns_no_facts_text_when_page_has_no_recognized_tags(monkeypatch):
    monkeypatch.setattr(dai_oakes_marketing.httpx, "Client", lambda **kw: _FakeClient(_FakeResponse(200, "<html><body>nothing useful</body></html>")))
    facts, sources = dai_oakes_marketing._fetch_dai_oakes_facts()
    assert facts == dai_oakes_marketing._NO_FACTS_TEXT
    assert sources == []


# --- run_generate_content -----------------------------------------------------------------

def test_generate_content_creates_a_pending_draft(monkeypatch):
    with session_scope() as session:
        session.query(DaiOakesMarketingContentRecord).delete()
    monkeypatch.setattr(dai_oakes_marketing, "_fetch_dai_oakes_facts", lambda: ("Clínica de fisioterapia em Roterdão.", ["meta description"]))
    monkeypatch.setattr(dai_oakes_marketing, "_call_model", lambda system, prompt, schema, name: _tool_response(
        dai_oakes_marketing.SUBMIT_CONTENT_TOOL_NAME, {"format": "instagram_post", "title": "Cuida do teu core", "body": "Vem conhecer os nossos serviços."},
    ))

    dai_oakes_marketing.run_generate_content()

    content = _latest_content()
    assert content is not None
    assert content.status == "pending_approval"
    assert content.format == "instagram_post"
    assert content.title == "Cuida do teu core"
    assert "meta description" in content.source_facts


def test_generate_content_does_not_pile_up_when_a_draft_is_already_pending(monkeypatch):
    with session_scope() as session:
        session.query(DaiOakesMarketingContentRecord).delete()
        session.add(DaiOakesMarketingContentRecord(format="instagram_post", title="Existing", body="Existing body", status="pending_approval"))

    def _forbidden(*a, **k):
        raise AssertionError("must not generate a second draft while one is still pending review")

    monkeypatch.setattr(dai_oakes_marketing, "_call_model", _forbidden)

    dai_oakes_marketing.run_generate_content()  # must not raise / must not call the model

    with session_scope() as session:
        assert session.query(DaiOakesMarketingContentRecord).count() == 1


def test_generate_content_generates_again_once_previous_draft_was_approved(monkeypatch):
    with session_scope() as session:
        session.query(DaiOakesMarketingContentRecord).delete()
        session.add(DaiOakesMarketingContentRecord(format="instagram_post", title="Approved one", body="body", status="approved"))
    monkeypatch.setattr(dai_oakes_marketing, "_fetch_dai_oakes_facts", lambda: ("facts", ["title"]))
    monkeypatch.setattr(dai_oakes_marketing, "_call_model", lambda system, prompt, schema, name: _tool_response(
        dai_oakes_marketing.SUBMIT_CONTENT_TOOL_NAME, {"format": "facebook_post", "title": "New one", "body": "body"},
    ))

    dai_oakes_marketing.run_generate_content()

    with session_scope() as session:
        assert session.query(DaiOakesMarketingContentRecord).count() == 2


def test_generate_content_no_tool_use_is_recorded_as_failed(monkeypatch):
    with session_scope() as session:
        session.query(DaiOakesMarketingContentRecord).delete()
    monkeypatch.setattr(dai_oakes_marketing, "_fetch_dai_oakes_facts", lambda: ("facts", ["title"]))
    monkeypatch.setattr(dai_oakes_marketing, "_call_model", lambda system, prompt, schema, name: SimpleNamespace(
        content=[{"type": "text", "text": "uncertain"}], stop_reason="end_turn", input_tokens=10, output_tokens=5,
    ))

    dai_oakes_marketing.run_generate_content()

    with session_scope() as session:
        audit = session.scalar(select(AuditRecord).where(AuditRecord.type == "dai_oakes_marketing_content_failed").order_by(AuditRecord.id.desc()))
        assert audit is not None
        assert "end_turn" in audit.detail
    assert _latest_content() is None


def test_generate_content_model_exception_is_recorded_as_failed_not_raised(monkeypatch):
    with session_scope() as session:
        session.query(DaiOakesMarketingContentRecord).delete()

    def _boom(system, prompt, schema, name):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(dai_oakes_marketing, "_fetch_dai_oakes_facts", lambda: ("facts", ["title"]))
    monkeypatch.setattr(dai_oakes_marketing, "_call_model", _boom)

    dai_oakes_marketing.run_generate_content()  # must not raise

    with session_scope() as session:
        audit = session.scalar(select(AuditRecord).where(AuditRecord.type == "dai_oakes_marketing_content_failed").order_by(AuditRecord.id.desc()))
        assert audit is not None
        assert "simulated API failure" in audit.detail


# --- run_marketing_sweep -------------------------------------------------------------------

def test_run_marketing_sweep_never_raises_on_total_failure(monkeypatch):
    def _boom():
        raise RuntimeError("simulated catastrophic failure")

    monkeypatch.setattr(dai_oakes_marketing, "run_generate_content", _boom)

    dai_oakes_marketing.run_marketing_sweep()  # must not raise

    with session_scope() as session:
        audit = session.scalar(select(AuditRecord).where(AuditRecord.type == "dai_oakes_marketing_sweep_failed").order_by(AuditRecord.id.desc()))
        assert audit is not None


# --- _seconds_until_sweep_due -- a restart/redeploy must never trigger an extra paid
# LLM call just because the process happened to restart ----------------------------------

def test_seconds_until_sweep_due_is_zero_when_no_content_exists():
    with session_scope() as session:
        session.query(DaiOakesMarketingContentRecord).delete()
    assert dai_oakes_marketing._seconds_until_sweep_due() == 0.0


def test_seconds_until_sweep_due_is_positive_right_after_content_created():
    with session_scope() as session:
        session.add(DaiOakesMarketingContentRecord(format="instagram_post", title="t", body="b", status="pending_approval"))
    pending = dai_oakes_marketing._seconds_until_sweep_due()
    assert 0 < pending <= dai_oakes_marketing.SWEEP_INTERVAL_SECONDS


def test_seconds_until_sweep_due_is_zero_once_interval_has_elapsed():
    from datetime import datetime, timedelta, timezone
    with session_scope() as session:
        session.query(DaiOakesMarketingContentRecord).delete()
        stale = datetime.now(timezone.utc) - timedelta(seconds=dai_oakes_marketing.SWEEP_INTERVAL_SECONDS + 60)
        session.add(DaiOakesMarketingContentRecord(format="instagram_post", title="t", body="b", status="approved", created_at=stale))
    assert dai_oakes_marketing._seconds_until_sweep_due() == 0.0


# --- run_sweep gating / start_dai_oakes_marketing -----------------------------------------

def test_start_dai_oakes_marketing_does_nothing_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(dai_oakes_marketing, "_started", False)

    dai_oakes_marketing.start_dai_oakes_marketing()

    assert dai_oakes_marketing._started is False


def test_start_dai_oakes_marketing_starts_a_thread_when_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(dai_oakes_marketing, "_started", False)
    started_threads = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started_threads.append((target, name, daemon))

        def start(self):
            pass  # deliberately never actually run the loop -- no real thread, no network

    monkeypatch.setattr(dai_oakes_marketing.threading, "Thread", _FakeThread)

    dai_oakes_marketing.start_dai_oakes_marketing()

    assert dai_oakes_marketing._started is True
    assert len(started_threads) == 1
    assert started_threads[0][1] == "volt-core-dai-oakes-marketing"
