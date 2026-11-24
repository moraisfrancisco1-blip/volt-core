from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from app.agents import agent_inbox, chief_of_staff, github_tools, knowledge_base, project_agent
from app.db import session_scope
from app.main import app
from app.models import AuditRecord, KBEntryRecord, ProjectHealthRecord, ProjectRecord

NOW = datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)
SECRET = "sk-abcdefghijklmnopqrstuvwx"


def _clear():
    with session_scope() as s:
        for m in (KBEntryRecord, ProjectHealthRecord, ProjectRecord):
            s.query(m).delete()


def _project(key="demo", repo="o/demo", confirmed=True, expect_public=False, status="active"):
    with session_scope() as s:
        s.add(ProjectRecord(key=key, name=key.title(), repo=repo, repo_confirmed=confirmed, expect_public=expect_public, status=status))


class FakeGitHub:
    """Stands in for github_tools._github_request. Routes by path; records every call."""
    def __init__(self, *, private=True, pushed_days_ago=2, pr_age_days=None, conclusions=("success",), docs=None, status=200):
        self.calls, self.private, self.status = [], private, status
        self.pushed = (NOW - timedelta(days=pushed_days_ago)).isoformat().replace("+00:00", "Z")
        self.pr_age = pr_age_days
        self.conclusions = conclusions
        self.docs = docs if docs is not None else {"README.md": "# Demo\nA demo project about energy trading."}

    def __call__(self, method, path, **kw):
        self.calls.append((method, path))
        def resp(code, js=None, text=""):
            return httpx.Response(code, json=js) if js is not None else httpx.Response(code, text=text)
        if path == "/repos/o/demo":
            return resp(self.status, {"private": self.private, "pushed_at": self.pushed, "default_branch": "main"}) if self.status == 200 else resp(self.status, {})
        if path == "/repos/o/demo/pulls":
            created = (NOW - timedelta(days=self.pr_age)).isoformat().replace("+00:00", "Z") if self.pr_age is not None else None
            return resp(200, [{"created_at": created}] if created else [])
        if path == "/repos/o/demo/commits/main/check-runs":
            return resp(200, {"check_runs": [{"status": "completed", "conclusion": c} for c in self.conclusions]})
        if path == "/repos/o/demo/git/trees/main":
            return resp(200, {"tree": [{"type": "blob", "path": p, "sha": f"sha-{hash(t) & 0xffff}"} for p, t in self.docs.items()] + [{"type": "blob", "path": ".env", "sha": "x"}, {"type": "blob", "path": "src/app.py", "sha": "y"}]})
        if path.startswith("/repos/o/demo/contents/"):
            name = path.split("/contents/")[1]
            return resp(200, text=self.docs[name]) if name in self.docs else resp(404, {})
        return resp(404, {})


# ---------- knowledge base
def test_kb_add_search_scopes_and_ranks():
    _clear()
    knowledge_base.add_entry(title="Regras de preço", body="Nunca inventar preços; vêm da config Stripe.", tags=["preços"])
    knowledge_base.add_entry(title="Brievo", body="Explica cartas neerlandesas.", project_key="brievo")
    knowledge_base.add_entry(title="Mesa", body="Funding do perpétuo contra spot.", project_key="mesa-de-funding")
    keys = lambda r: [h["title"] for h in r]
    assert keys(knowledge_base.search("preços", project_key="brievo")) == ["Regras de preço"]          # shared entry visible to every project
    assert "Mesa" not in keys(knowledge_base.search("funding perpétuo spot", project_key="brievo"))    # other project's entry hidden
    assert keys(knowledge_base.search("funding perpétuo spot")) == ["Mesa"]                            # no scope = everything
    assert knowledge_base.search("ab") == []


def test_kb_refuses_secrets_and_stores_nothing():
    _clear()
    try:
        knowledge_base.add_entry(title="Chaves", body=f"a chave é {SECRET}")
        assert False
    except knowledge_base.KBRefused as exc:
        assert "secret_api_key" in str(exc) and SECRET not in str(exc)
    with session_scope() as s:
        assert s.query(KBEntryRecord).count() == 0


def test_kb_context_for_and_archive():
    _clear()
    e = knowledge_base.add_entry(title="Contexto", body="O Volt Core nunca aprova sozinho em produção.", project_key="volt-core")
    assert "nunca aprova" in knowledge_base.context_for("volt-core", "aprova produção")
    assert knowledge_base.archive_entry(e["id"]) is True
    assert knowledge_base.context_for("volt-core", "aprova produção") == ""
    assert knowledge_base.archive_entry(999999) is False


def test_kb_endpoints():
    _clear()
    with TestClient(app) as c:
        assert c.post("/api/kb/entries", json={"title": "T", "body": f"x {SECRET}"}).status_code == 422
        ok = c.post("/api/kb/entries", json={"title": "Nota", "body": "Texto sobre energia", "tags": ["a"]})
        assert ok.status_code == 200
        assert c.get("/api/kb/search", params={"q": "energia"}).json()[0]["title"] == "Nota"
        assert c.post(f"/api/kb/entries/{ok.json()['id']}/archive").json()["status"] == "archived"
        assert c.get("/api/kb/entries").json() == []


# ---------- project registry
def test_seed_defaults_is_idempotent_and_flags_unconfirmed_repos():
    _clear()
    first, second = project_agent.seed_default_projects(), project_agent.seed_default_projects()
    assert first["created"] == len(project_agent.DEFAULT_PROJECTS) and second["created"] == 0
    with session_scope() as s:
        mesa = s.query(ProjectRecord).filter_by(key="mesa-de-funding").one()
        assert mesa.repo is None and mesa.repo_confirmed is False


# ---------- project steward (+ L3 sub-checkers)
def test_steward_healthy_private_repo_syncs_docs_and_skips_noise(monkeypatch):
    _clear(); _project()
    fake = FakeGitHub(); monkeypatch.setattr(github_tools, "_github_request", fake)
    r = project_agent.run_project_steward("demo", now=NOW)
    assert r["flags"] == [] and r["kb_sync"]["created"] == 1
    fetched = [p for _, p in fake.calls if "/contents/" in p]
    assert fetched == ["/repos/o/demo/contents/README.md"]       # .env and src/app.py never requested
    with session_scope() as s:
        assert s.query(ProjectHealthRecord).filter_by(project_key="demo").one().ci_state == "passing"


def test_steward_flags_exposure_ci_stale_pr_and_stale_repo(monkeypatch):
    _clear(); _project()
    monkeypatch.setattr(github_tools, "_github_request", FakeGitHub(private=False, pushed_days_ago=90, pr_age_days=12, conclusions=("success", "failure")))
    flags = project_agent.run_project_steward("demo", now=NOW)["flags"]
    assert {"public_repo_unexpected", "stale_repo", "stale_prs", "ci_failing"} <= set(flags)


def test_expect_public_suppresses_exposure_flag(monkeypatch):
    _clear(); _project(expect_public=True)
    monkeypatch.setattr(github_tools, "_github_request", FakeGitHub(private=False))
    assert "public_repo_unexpected" not in project_agent.run_project_steward("demo", now=NOW)["flags"]


def test_steward_handles_unreachable_repo_and_missing_repo(monkeypatch):
    _clear(); _project(); _project(key="norepo", repo=None, confirmed=False)
    monkeypatch.setattr(github_tools, "_github_request", FakeGitHub(status=404))
    r = project_agent.run_project_steward("demo", now=NOW)
    assert "repo_unreachable" in r["flags"] and "repo not reachable" in r["error"]
    assert "no_repo" in project_agent.run_project_steward("norepo", now=NOW)["flags"]
    assert project_agent.run_project_steward("nope")["ran"] is False


def test_kb_sync_is_idempotent_updates_on_change_and_refuses_secrets(monkeypatch):
    _clear(); _project()
    fake = FakeGitHub(); monkeypatch.setattr(github_tools, "_github_request", fake)
    assert project_agent.run_project_steward("demo", now=NOW)["kb_sync"]["created"] == 1
    again = project_agent.run_project_steward("demo", now=NOW)["kb_sync"]
    assert again["unchanged"] == 1 and again["created"] == 0
    fake.docs = {"README.md": "# Demo v2, texto novo"}
    assert project_agent.run_project_steward("demo", now=NOW)["kb_sync"]["updated"] == 1
    fake.docs = {"README.md": f"# Demo\nkey {SECRET}"}
    r = project_agent.run_project_steward("demo", now=NOW)
    assert r["kb_sync"]["refused"] == 1 and "kb_secret_refused" in r["flags"]
    with session_scope() as s:
        assert SECRET not in s.query(KBEntryRecord).one().body                                   # previous clean version kept
        assert all(SECRET not in (a.detail or "") for a in s.query(AuditRecord).filter_by(type="kb_sync_refused"))


# ---------- chief of staff integration
def test_daily_cycle_runs_one_steward_per_active_project_then_briefing(monkeypatch):
    _clear(); _project(); _project(key="paused-one", status="paused")
    monkeypatch.setattr(agent_inbox, "_started", False)
    monkeypatch.setattr(github_tools, "_github_request", FakeGitHub(private=False))
    with TestClient(app) as c:
        result = c.post("/api/governance/daily-cycle").json()
        assert result["ran"][-2:] == ["project_steward:demo", "daily_briefing"] and "project_steward:paused-one" not in result["ran"]
        b = c.get("/api/governance/briefings").json()[0]
        assert "Projeto Demo: public_repo_unexpected" in b["summary"] and b["attention_count"] >= 1
        assert b["data"]["projects"][0]["key"] == "demo"


def test_one_failing_steward_does_not_stop_the_briefing(monkeypatch):
    _clear(); _project()
    monkeypatch.setattr(agent_inbox, "_started", False)
    monkeypatch.setattr(project_agent, "run_project_steward", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    result = chief_of_staff.start_daily_cycle()
    assert result["ran"][-1] == "daily_briefing"
    with session_scope() as s:
        assert s.query(AuditRecord).filter_by(type="daily_cycle_step_failed", reference_id="project_steward").count() >= 1


def test_inbox_dispatch_routes_project_steward(monkeypatch):
    _clear(); _project()
    monkeypatch.setattr(github_tools, "_github_request", FakeGitHub())
    agent_inbox._dispatch("project_steward", {"project_key": "demo"})
    with session_scope() as s:
        assert s.query(ProjectHealthRecord).filter_by(project_key="demo").count() == 1


def test_project_endpoints(monkeypatch):
    _clear()
    monkeypatch.setattr(github_tools, "_github_request", FakeGitHub())
    with TestClient(app) as c:
        assert c.post("/api/projects", json={"key": "demo", "name": "Demo", "repo": "o/demo", "repo_confirmed": True}).status_code == 200
        assert c.post("/api/projects", json={"key": "Bad Key", "name": "x"}).status_code == 422
        assert c.post("/api/projects", json={"key": "k2", "name": "x", "kind": "weird"}).status_code == 422
        assert c.post("/api/projects/demo/steward/run").json()["ran"] is True
        assert c.post("/api/projects/ghost/steward/run").status_code == 404
        assert c.get("/api/projects/demo/health").json()[0]["ci_state"] == "passing"
