import io
import os
import tarfile
import tempfile
from types import SimpleNamespace

from app.agents import github_tools
from app.agents.github_tools import CodeDiagnosisJob
from app.db import session_scope
from app.models import AgentInvestigationRecord


def _job(**overrides) -> CodeDiagnosisJob:
    defaults = dict(event_id=1, escalation_id=2, system="probe-system", environment="production", priority="P2", owner="acme", repo="widget", parent_investigation_id=99)
    defaults.update(overrides)
    return CodeDiagnosisJob(**defaults)


def _fake_response(status_code=200, json_data=None, text="", headers=None):
    return SimpleNamespace(status_code=status_code, json=lambda: json_data, text=text, headers=headers or {})


def test_is_noise_excludes_build_artifacts_but_not_legit_files_with_similar_names():
    assert github_tools._is_noise("frontend/node_modules/react/index.js")
    assert github_tools._is_noise("landing/.next/cache/webpack/0.pack")
    assert github_tools._is_noise("package-lock.json")
    assert github_tools._is_noise("frontend/.npm-cache/_cacache/content-v2/foo")
    # Real files that merely contain a noise substring must NOT be excluded.
    assert not github_tools._is_noise("packages/desktop/electron-builder.json5")
    assert not github_tools._is_noise("backend/builder.py")
    assert not github_tools._is_noise("src/rebuild-utils.ts")


def test_is_sensitive_refuses_secrets_but_allows_examples():
    assert github_tools._is_sensitive(".env")
    assert github_tools._is_sensitive("backend/.env.local")
    assert github_tools._is_sensitive("keys/id_rsa")
    assert github_tools._is_sensitive("config/secrets.py")
    assert github_tools._is_sensitive("infra/credentials.json")
    assert github_tools._is_sensitive("certs/server.pem")
    assert not github_tools._is_sensitive(".env.example")
    assert not github_tools._is_sensitive(".env.template")
    assert not github_tools._is_sensitive("backend/main.py")


def test_read_repo_file_refuses_sensitive_path_without_any_network_call(monkeypatch):
    def spy(*args, **kwargs):
        raise AssertionError("_github_request must not be called for a sensitive path")

    monkeypatch.setattr(github_tools, "_github_request", spy)
    result = github_tools.read_repo_file(_job(), ".env")
    assert result["refused"] is True
    assert result["reason"] == "refused: sensitive file pattern"


def test_read_repo_file_success(monkeypatch):
    monkeypatch.setattr(github_tools, "_github_request", lambda method, path, **kw: _fake_response(200, text="print('hi')", headers={"content-type": "application/vnd.github.raw+json; charset=utf-8"}))
    result = github_tools.read_repo_file(_job(), "backend/main.py")
    assert result["content"] == "print('hi')"
    assert result["truncated"] is False


def test_read_repo_file_truncates_large_files(monkeypatch):
    big = "x" * (github_tools.MAX_FILE_CHARS + 500)
    monkeypatch.setattr(github_tools, "_github_request", lambda method, path, **kw: _fake_response(200, text=big, headers={"content-type": "application/vnd.github.raw+json"}))
    result = github_tools.read_repo_file(_job(), "backend/big.py")
    assert result["truncated"] is True
    assert len(result["content"]) == github_tools.MAX_FILE_CHARS
    assert result["total_chars"] == len(big)


def test_read_repo_file_detects_directory_via_content_type(monkeypatch):
    monkeypatch.setattr(github_tools, "_github_request", lambda method, path, **kw: _fake_response(200, json_data=[], headers={"content-type": "application/json; charset=utf-8"}))
    result = github_tools.read_repo_file(_job(), "backend")
    assert "directory" in result["error"]


def test_read_repo_file_404(monkeypatch):
    monkeypatch.setattr(github_tools, "_github_request", lambda method, path, **kw: _fake_response(404))
    result = github_tools.read_repo_file(_job(), "nope.py")
    assert "not found" in result["error"]


def test_read_repo_file_network_failure(monkeypatch):
    monkeypatch.setattr(github_tools, "_github_request", lambda method, path, **kw: None)
    result = github_tools.read_repo_file(_job(), "backend/main.py")
    assert "network/transport error" in result["error"]


def test_list_repo_files_resolves_branch_then_lists_and_filters_noise(monkeypatch):
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append(path)
        if path == "/repos/acme/widget":
            return _fake_response(200, json_data={"default_branch": "master"})
        if path == "/repos/acme/widget/git/trees/master":
            return _fake_response(200, json_data={
                "truncated": False,
                "tree": [
                    {"path": "backend/main.py", "type": "blob"},
                    {"path": "backend/node_modules/x.js", "type": "blob"},
                    {"path": "backend", "type": "tree"},
                    {"path": "package-lock.json", "type": "blob"},
                    {"path": "packages/desktop/electron-builder.json5", "type": "blob"},
                ],
            })
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(github_tools, "_github_request", fake_request)
    result = github_tools.list_repo_files(_job())
    assert calls[0] == "/repos/acme/widget"
    assert "backend/main.py" in result["files"]
    assert "packages/desktop/electron-builder.json5" in result["files"]
    assert not any("node_modules" in f for f in result["files"])
    assert "package-lock.json" not in result["files"]
    assert result["listing_truncated_by_github"] is False


def test_list_repo_files_scopes_to_subdirectory(monkeypatch):
    def fake_request(method, path, **kwargs):
        if path == "/repos/acme/widget":
            return _fake_response(200, json_data={"default_branch": "main"})
        return _fake_response(200, json_data={"truncated": False, "tree": [
            {"path": "backend/main.py", "type": "blob"},
            {"path": "frontend/App.jsx", "type": "blob"},
        ]})

    monkeypatch.setattr(github_tools, "_github_request", fake_request)
    result = github_tools.list_repo_files(_job(), path="backend")
    assert result["files"] == ["backend/main.py"]


def test_list_repo_files_default_branch_failure_short_circuits(monkeypatch):
    def fake_request(method, path, **kwargs):
        if path == "/repos/acme/widget":
            return _fake_response(404)
        raise AssertionError("should not reach the trees endpoint")

    monkeypatch.setattr(github_tools, "_github_request", fake_request)
    result = github_tools.list_repo_files(_job())
    assert "could not resolve default branch" in result["error"]


def test_search_repo_code_success_filters_noise(monkeypatch):
    def fake_request(method, path, **kwargs):
        assert path == "/search/code"
        assert "repo:acme/widget" in kwargs["params"]["q"]
        return _fake_response(200, json_data={
            "total_count": 2,
            "items": [
                {"path": "backend/routers/payments.py", "text_matches": [{"fragment": "stripe.charge"}]},
                {"path": "frontend/node_modules/x/payments.js", "text_matches": []},
            ],
        })

    monkeypatch.setattr(github_tools, "_github_request", fake_request)
    result = github_tools.search_repo_code(_job(), "stripe")
    assert result["total_count"] == 2
    assert [item["path"] for item in result["items"]] == ["backend/routers/payments.py"]
    assert result["items"][0]["fragments"] == ["stripe.charge"]


def test_search_repo_code_rate_limited(monkeypatch):
    monkeypatch.setattr(github_tools, "_github_request", lambda method, path, **kw: _fake_response(403))
    result = github_tools.search_repo_code(_job(), "anything")
    assert "rate limit" in result["error"]


def test_get_recent_commits_success(monkeypatch):
    monkeypatch.setattr(github_tools, "_github_request", lambda method, path, **kw: _fake_response(200, json_data=[
        {"sha": "a" * 40, "commit": {"author": {"name": "Dev", "date": "2026-08-30T00:00:00Z"}, "message": "fix: bug\n\nmore detail"}},
    ]))
    result = github_tools.get_recent_commits(_job(), limit=5)
    commit = result["commits"][0]
    assert commit["sha"] == "a" * 12
    assert commit["author"] == "Dev"
    assert commit["message"] == "fix: bug"


def test_get_prior_investigation_reads_from_db():
    with session_scope() as session:
        record = AgentInvestigationRecord(
            event_id=1, escalation_id=2, investigation_type="voice_call_failure",
            system="probe-system", environment="production", priority="P2", status="completed",
            hypothesis="Looks like a transient network blip", recommended_next_step="Monitor for recurrence",
            confidence=0.4, is_known_pattern=False,
        )
        session.add(record)
        session.flush()
        parent_id = record.id

    result = github_tools.get_prior_investigation(_job(parent_investigation_id=parent_id))
    assert result["id"] == parent_id
    assert result["hypothesis"] == "Looks like a transient network blip"
    assert result["is_known_pattern"] is False


def test_get_prior_investigation_missing():
    result = github_tools.get_prior_investigation(_job(parent_investigation_id=999999))
    assert result == {"error": "prior investigation not found"}


def _build_fake_tarball_bytes(nested_dir_name: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        file_content = b"print('hello')\n"
        info = tarfile.TarInfo(name=f"{nested_dir_name}/main.py")
        info.size = len(file_content)
        archive.addfile(info, io.BytesIO(file_content))
    return buffer.getvalue()


def test_download_repo_tarball_success(monkeypatch):
    tarball_bytes = _build_fake_tarball_bytes("acme-widget-abc123")
    monkeypatch.setattr(github_tools, "_github_request", lambda method, path, **kwargs: SimpleNamespace(status_code=200, content=tarball_bytes))

    dest_dir = tempfile.mkdtemp(prefix="github-tarball-test-")
    root = github_tools.download_repo_tarball("acme", "widget", dest_dir)

    assert root == os.path.join(dest_dir, "acme-widget-abc123")
    assert os.path.exists(os.path.join(root, "main.py"))


def test_download_repo_tarball_returns_none_on_non_200(monkeypatch):
    monkeypatch.setattr(github_tools, "_github_request", lambda method, path, **kwargs: SimpleNamespace(status_code=404, content=b""))

    dest_dir = tempfile.mkdtemp(prefix="github-tarball-test-")
    assert github_tools.download_repo_tarball("acme", "widget", dest_dir) is None


def test_download_repo_tarball_returns_none_on_transport_failure(monkeypatch):
    monkeypatch.setattr(github_tools, "_github_request", lambda method, path, **kwargs: None)

    dest_dir = tempfile.mkdtemp(prefix="github-tarball-test-")
    assert github_tools.download_repo_tarball("acme", "widget", dest_dir) is None


def test_download_repo_tarball_returns_none_on_corrupt_archive(monkeypatch):
    monkeypatch.setattr(github_tools, "_github_request", lambda method, path, **kwargs: SimpleNamespace(status_code=200, content=b"not a real tarball"))

    dest_dir = tempfile.mkdtemp(prefix="github-tarball-test-")
    assert github_tools.download_repo_tarball("acme", "widget", dest_dir) is None
