import os
import tempfile

import pytest

from app.agents import sandbox


def _fresh_dir():
    # Matches production's real nesting: _materialize_repo returns
    # os.path.join(dest_dir, extracted_subdir), and run_sandboxed_fix cleans up via
    # os.path.dirname(root) == dest_dir. Tests that stub _materialize_repo must return
    # a path with this same shape, or run_sandboxed_fix's cleanup would rmtree the
    # system temp root itself instead of a per-test sandbox directory.
    sandbox_tempdir = tempfile.mkdtemp(prefix="sandbox-test-")
    root = os.path.join(sandbox_tempdir, "extracted")
    os.makedirs(root)
    return root


# --- _validate_relative_path -- the injection-defense choke point ------------------

def test_validate_relative_path_rejects_parent_traversal():
    root = _fresh_dir()
    assert sandbox._validate_relative_path(root, "../../etc/passwd") is None


def test_validate_relative_path_rejects_absolute_path():
    root = _fresh_dir()
    assert sandbox._validate_relative_path(root, "/etc/passwd") is None


def test_validate_relative_path_rejects_mixed_traversal():
    root = _fresh_dir()
    assert sandbox._validate_relative_path(root, "a/../../b") is None


def test_validate_relative_path_rejects_empty_string():
    root = _fresh_dir()
    assert sandbox._validate_relative_path(root, "") is None


def test_validate_relative_path_accepts_normal_nested_path():
    root = _fresh_dir()
    result = sandbox._validate_relative_path(root, "app/models.py")
    assert result == os.path.realpath(os.path.join(root, "app/models.py"))


# --- _apply_proposed_files -- never touches disk on a rejected path ----------------

def test_apply_proposed_files_rejects_unsafe_path_without_writing_anything(monkeypatch):
    root = _fresh_dir()

    def _forbidden_open(*args, **kwargs):
        raise AssertionError("open() must not be called for a rejected file_path")

    monkeypatch.setattr("builtins.open", _forbidden_open)

    error = sandbox._apply_proposed_files(root, [{"file_path": "../../etc/passwd", "new_content": "x"}])

    assert error is not None
    assert "rejected" in error


def test_apply_proposed_files_writes_valid_files():
    root = _fresh_dir()
    error = sandbox._apply_proposed_files(root, [{"file_path": "pkg/mod.py", "new_content": "x = 1\n"}])

    assert error is None
    with open(os.path.join(root, "pkg", "mod.py")) as f:
        assert f.read() == "x = 1\n"


def test_apply_proposed_files_rejects_malformed_entry():
    root = _fresh_dir()
    error = sandbox._apply_proposed_files(root, [{"file_path": "x.py"}])  # missing new_content
    assert error is not None


# --- _detect_stack -------------------------------------------------------------------

def test_detect_stack_true_with_requirements_and_test_file():
    root = _fresh_dir()
    with open(os.path.join(root, "requirements.txt"), "w") as f:
        f.write("pytest\n")
    with open(os.path.join(root, "test_sample.py"), "w") as f:
        f.write("def test_x(): assert True\n")
    assert sandbox._detect_stack(root) is True


def test_detect_stack_false_without_manifest():
    root = _fresh_dir()
    with open(os.path.join(root, "test_sample.py"), "w") as f:
        f.write("def test_x(): assert True\n")
    assert sandbox._detect_stack(root) is False


def test_detect_stack_false_without_test_files():
    root = _fresh_dir()
    with open(os.path.join(root, "requirements.txt"), "w") as f:
        f.write("pytest\n")
    assert sandbox._detect_stack(root) is False


# --- _scrubbed_env -- the credential-leak proof -------------------------------------

def test_scrubbed_env_never_leaks_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-github-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod-secret")
    monkeypatch.setenv("STRIPE_SECRET_KEY_FOO", "fake-stripe-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = sandbox._scrubbed_env(home="/tmp/whatever")

    assert "GITHUB_TOKEN" not in env
    assert "DATABASE_URL" not in env
    assert "STRIPE_SECRET_KEY_FOO" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/tmp/whatever"


def test_scrubbed_env_only_contains_allowlisted_plus_home(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("SOME_RANDOM_VAR", "should-not-appear")

    env = sandbox._scrubbed_env(home="/tmp/whatever")

    assert set(env.keys()) <= {"PATH", "LANG", "LC_ALL", "PYTHONPATH", "HOME"}
    assert "SOME_RANDOM_VAR" not in env


# --- run_sandboxed_fix orchestration (internals mocked) -----------------------------

def test_run_sandboxed_fix_returns_error_without_running_anything_for_unsafe_path(monkeypatch):
    root = _fresh_dir()
    monkeypatch.setattr(sandbox, "_materialize_repo", lambda owner, repo: root)

    def _forbidden(*a, **k):
        raise AssertionError("must not run install/pytest when a proposed file is rejected")

    monkeypatch.setattr(sandbox, "_run_phase1_install", _forbidden)
    monkeypatch.setattr(sandbox, "_run_phase2_pytest", _forbidden)

    result = sandbox.run_sandboxed_fix("acme", "widget", [{"file_path": "/etc/passwd", "new_content": "x"}])

    assert result["status"] == "error"
    assert "rejected" in result["output"]


def test_run_sandboxed_fix_returns_error_when_materialize_fails(monkeypatch):
    monkeypatch.setattr(sandbox, "_materialize_repo", lambda owner, repo: None)

    result = sandbox.run_sandboxed_fix("acme", "widget", [{"file_path": "a.py", "new_content": "x"}])

    assert result["status"] == "error"


def test_run_sandboxed_fix_returns_unsupported_stack(monkeypatch):
    root = _fresh_dir()
    monkeypatch.setattr(sandbox, "_materialize_repo", lambda owner, repo: root)
    monkeypatch.setattr(sandbox, "_detect_stack", lambda r: False)

    def _forbidden(*a, **k):
        raise AssertionError("must not run install/pytest for an unsupported stack")

    monkeypatch.setattr(sandbox, "_run_phase1_install", _forbidden)
    monkeypatch.setattr(sandbox, "_run_phase2_pytest", _forbidden)

    result = sandbox.run_sandboxed_fix("acme", "widget", [{"file_path": "a.py", "new_content": "x"}])

    assert result["status"] == "unsupported_stack"


def test_run_sandboxed_fix_happy_path_passed(monkeypatch):
    root = _fresh_dir()
    monkeypatch.setattr(sandbox, "_materialize_repo", lambda owner, repo: root)
    monkeypatch.setattr(sandbox, "_detect_stack", lambda r: True)
    monkeypatch.setattr(sandbox, "_chown_tree_to_sandbox_user", lambda r: False)
    monkeypatch.setattr(sandbox, "_run_phase1_install", lambda r, t, u: (True, "installed ok"))
    monkeypatch.setattr(sandbox, "_run_phase2_pytest", lambda r, t, u: ("passed", "1 passed", True))

    result = sandbox.run_sandboxed_fix("acme", "widget", [{"file_path": "a.py", "new_content": "x = 1\n"}])

    assert result["status"] == "passed"
    assert result["output"] == "1 passed"
    assert result["network_isolated"] is True


def test_run_sandboxed_fix_reports_install_failure(monkeypatch):
    root = _fresh_dir()
    monkeypatch.setattr(sandbox, "_materialize_repo", lambda owner, repo: root)
    monkeypatch.setattr(sandbox, "_detect_stack", lambda r: True)
    monkeypatch.setattr(sandbox, "_chown_tree_to_sandbox_user", lambda r: False)
    monkeypatch.setattr(sandbox, "_run_phase1_install", lambda r, t, u: (False, "pip explosion"))

    def _forbidden(*a, **k):
        raise AssertionError("must not run pytest when install failed")

    monkeypatch.setattr(sandbox, "_run_phase2_pytest", _forbidden)

    result = sandbox.run_sandboxed_fix("acme", "widget", [{"file_path": "a.py", "new_content": "x"}])

    assert result["status"] == "error"
    assert result["install_output"] == "pip explosion"


def test_run_sandboxed_fix_cleans_up_even_when_a_phase_raises(monkeypatch):
    root = _fresh_dir()
    cleaned_up = []
    monkeypatch.setattr(sandbox, "_materialize_repo", lambda owner, repo: root)
    monkeypatch.setattr(sandbox, "_detect_stack", lambda r: True)
    monkeypatch.setattr(sandbox, "_chown_tree_to_sandbox_user", lambda r: False)

    def _boom(r, t, u):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(sandbox, "_run_phase1_install", _boom)
    original_rmtree = sandbox.shutil.rmtree

    def _tracked_rmtree(path, ignore_errors=False):
        cleaned_up.append(path)
        return original_rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(sandbox.shutil, "rmtree", _tracked_rmtree)

    result = sandbox.run_sandboxed_fix("acme", "widget", [{"file_path": "a.py", "new_content": "x"}])

    assert result["status"] == "error"
    assert "simulated crash" in result["output"]
    assert len(cleaned_up) == 1
    assert not os.path.exists(cleaned_up[0])
