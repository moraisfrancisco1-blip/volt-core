from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import github_tools, marketing_agent
from app.db import session_scope
from app.models import AuditRecord, MarketingContentRecord


@pytest.fixture(autouse=True)
def _default_provider_key(monkeypatch):
    # _call_model is always monkeypatched in this file's tests, so the real client is
    # never used -- but the module still calls llm_client.get_client() first, which
    # would raise LLMConfigError with no provider configured at all.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-not-real")


def _tool_response(tool_name, input_dict):
    return SimpleNamespace(
        content=[{"type": "tool_use", "name": tool_name, "input": input_dict, "id": "toolu_1"}],
        stop_reason="tool_use",
        input_tokens=50,
        output_tokens=20,
    )


def _seed_content(**overrides) -> int:
    defaults = dict(content_type="blog_post", format="blog", audience="consumer", title="Título", body="Corpo.", status="pending_approval")
    defaults.update(overrides)
    with session_scope() as session:
        content = MarketingContentRecord(**defaults)
        session.add(content)
        session.flush()
        return content.id


def _get_content(content_id: int) -> MarketingContentRecord:
    with session_scope() as session:
        row = session.get(MarketingContentRecord, content_id)
        session.expunge(row)
        return row


def _variants_of(parent_id: int) -> list[MarketingContentRecord]:
    with session_scope() as session:
        rows = session.scalars(select(MarketingContentRecord).where(MarketingContentRecord.parent_content_id == parent_id)).all()
        for row in rows:
            session.expunge(row)
        return rows


# --- _fetch_product_facts ----------------------------------------------------------------

def test_fetch_product_facts_without_repo_mapping(monkeypatch):
    monkeypatch.delenv("VOLT_SYSTEM_REPOS", raising=False)
    facts, sources = marketing_agent._fetch_product_facts()
    assert facts == marketing_agent._NO_FACTS_TEXT
    assert sources == []


def test_fetch_product_facts_reads_readme(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_REPOS", '{"voltaris-os": "acme/voltarisos"}')
    monkeypatch.setattr(github_tools, "read_repo_file", lambda job, path: {"content": "# VoltarisOS\nGestão de energia solar."} if path == "README.md" else {"error": "not found"})
    monkeypatch.setattr(github_tools, "list_repo_files", lambda job, path="": {"files": []})

    facts, sources = marketing_agent._fetch_product_facts()

    assert "Gestão de energia solar" in facts
    assert sources == ["README.md"]


def test_fetch_product_facts_reads_extra_docs(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_REPOS", '{"voltaris-os": "acme/voltarisos"}')

    def fake_read(job, path):
        if path == "README.md":
            return {"content": "README real."}
        if path in {"docs/features.md", "docs/pricing.md"}:
            return {"content": f"conteudo de {path}"}
        return {"error": "not found"}

    monkeypatch.setattr(github_tools, "read_repo_file", fake_read)
    monkeypatch.setattr(github_tools, "list_repo_files", lambda job, path="": {"files": ["docs/features.md", "docs/pricing.md", "docs/extra.md"]})

    facts, sources = marketing_agent._fetch_product_facts()

    assert "README real." in facts
    assert "docs/features.md" in sources
    assert "docs/pricing.md" in sources
    assert len(sources) == 3  # README + only the first 2 docs files, capped


def test_fetch_product_facts_degrades_when_readme_missing(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_REPOS", '{"voltaris-os": "acme/voltarisos"}')
    monkeypatch.setattr(github_tools, "read_repo_file", lambda job, path: {"error": "not found"})
    monkeypatch.setattr(github_tools, "list_repo_files", lambda job, path="": {"files": []})

    facts, sources = marketing_agent._fetch_product_facts()

    assert facts == marketing_agent._NO_FACTS_TEXT
    assert sources == []


# --- run_generate_content ----------------------------------------------------------------

def test_run_generate_content_persists_pending_blog_post(monkeypatch):
    monkeypatch.setattr(marketing_agent, "_fetch_product_facts", lambda: ("Factos reais.", ["README.md"]))
    monkeypatch.setattr(marketing_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        marketing_agent.SUBMIT_CONTENT_TOOL_NAME, {"title": "Como poupar com solar", "body": "Corpo do post.", "audience": "consumer"},
    ))

    marketing_agent.run_generate_content()

    with session_scope() as session:
        row = session.scalar(select(MarketingContentRecord).order_by(MarketingContentRecord.id.desc()))
        assert row.content_type == "blog_post"
        assert row.format == "blog"
        assert row.title == "Como poupar com solar"
        assert row.status == "pending_approval"
        assert row.source_facts == "README.md"


def test_run_generate_content_skips_when_a_pending_blog_already_exists(monkeypatch):
    _seed_content(content_type="blog_post", status="pending_approval")

    def _forbidden(*a, **k):
        raise AssertionError("must not generate a second pending blog post")

    monkeypatch.setattr(marketing_agent, "_call_model", _forbidden)

    marketing_agent.run_generate_content()  # must not raise / must not call the model


def test_run_generate_content_no_tool_use_is_recorded_as_failed(monkeypatch):
    # Other tests in this file may leave a pending_approval blog_post behind, which
    # would make run_generate_content's own dedup gate skip before ever reaching the
    # model call this test actually exercises -- clear that gate first.
    with session_scope() as session:
        for row in session.scalars(select(MarketingContentRecord).where(MarketingContentRecord.content_type == "blog_post", MarketingContentRecord.status == "pending_approval")).all():
            row.status = "approved"
    monkeypatch.setattr(marketing_agent, "_fetch_product_facts", lambda: ("Factos.", ["README.md"]))
    monkeypatch.setattr(marketing_agent, "_call_model", lambda system, prompt, schema, name: SimpleNamespace(
        content=[{"type": "text", "text": "uncertain"}], stop_reason="end_turn", input_tokens=10, output_tokens=5,
    ))
    with session_scope() as session:
        content_count_before = len(session.scalars(select(MarketingContentRecord)).all())

    marketing_agent.run_generate_content()

    with session_scope() as session:
        content_count_after = len(session.scalars(select(MarketingContentRecord)).all())
        failure_logged = session.scalar(select(AuditRecord).where(AuditRecord.type == "marketing_content_failed")) is not None
    assert content_count_after == content_count_before  # no row created for the failed attempt
    assert failure_logged is True


# --- run_repurpose_content ----------------------------------------------------------------

def test_run_repurpose_content_creates_variants_with_parent_link(monkeypatch):
    parent_id = _seed_content(title="Post original", body="Corpo original.")
    monkeypatch.setattr(marketing_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        marketing_agent.SUBMIT_REPURPOSE_TOOL_NAME,
        {"variants": [
            {"format": "linkedin_post", "title": "LinkedIn", "body": "Versão LinkedIn."},
            {"format": "twitter_post", "title": "Twitter", "body": "Versão Twitter."},
        ]},
    ))

    marketing_agent.run_repurpose_content(parent_id)

    variants = _variants_of(parent_id)
    assert len(variants) == 2
    assert {v.format for v in variants} == {"linkedin_post", "twitter_post"}
    assert all(v.parent_content_id == parent_id for v in variants)
    assert all(v.content_type == "social_post" for v in variants)


def test_run_repurpose_content_missing_content_does_nothing(monkeypatch):
    def _forbidden(*a, **k):
        raise AssertionError("must not call the model for a missing content id")

    monkeypatch.setattr(marketing_agent, "_call_model", _forbidden)

    marketing_agent.run_repurpose_content(999999)  # must not raise


# --- run_marketing_sweep -----------------------------------------------------------------

def test_run_marketing_sweep_one_failure_does_not_abort_the_rest(monkeypatch):
    def _boom():
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(marketing_agent, "run_generate_content", _boom)

    marketing_agent.run_marketing_sweep()  # must not raise


def test_run_marketing_sweep_repurposes_blog_posts_without_variants(monkeypatch):
    blog_id = _seed_content(content_type="blog_post", status="approved")
    monkeypatch.setattr(marketing_agent, "run_generate_content", lambda: None)
    calls = []
    monkeypatch.setattr(marketing_agent, "run_repurpose_content", lambda content_id: calls.append(content_id))

    marketing_agent.run_marketing_sweep()

    # Other tests in the same run may leave their own blog_post rows without variants
    # yet -- this only asserts that THIS test's blog post was picked up, not that it
    # was the only one.
    assert blog_id in calls


# --- start_marketing_agent ----------------------------------------------------------------

def test_start_marketing_agent_does_nothing_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(marketing_agent, "_started", False)

    marketing_agent.start_marketing_agent()

    assert marketing_agent._started is False


def test_start_marketing_agent_starts_a_thread_when_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(marketing_agent, "_started", False)
    started_threads = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started_threads.append((target, name, daemon))

        def start(self):
            pass  # deliberately never actually run the loop -- no real thread, no network

    monkeypatch.setattr(marketing_agent.threading, "Thread", _FakeThread)

    marketing_agent.start_marketing_agent()

    assert marketing_agent._started is True
    assert len(started_threads) == 1
    assert started_threads[0][1] == "volt-core-marketing"
