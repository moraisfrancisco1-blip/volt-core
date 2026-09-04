from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

from . import github_tools

MAX_OUTPUT_CHARS = 20_000
SANDBOX_USER = "voltsandbox"

# Explicit allowlist, never a blocklist -- nothing not named here reaches the sandboxed
# subprocess's environment, including dynamically-named vars (e.g. STRIPE_SECRET_KEY_*)
# that a blocklist could never enumerate completely.
_SAFE_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "PYTHONPATH")


def _validate_relative_path(root: str, file_path: str) -> str | None:
    # The injection-defense choke point: called before ANY open()/os.makedirs() touches
    # a filesystem path built from a proposed_files["file_path"] the model supplied.
    # Returns the safe absolute path, or None if the path is unsafe in any way.
    if not file_path or os.path.isabs(file_path) or "\x00" in file_path:
        return None
    normalized = file_path.replace("\\", "/")
    segments = normalized.split("/")
    if any(segment in ("", "..") for segment in segments):
        return None
    root_real = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root_real, normalized))
    if candidate != root_real and not candidate.startswith(root_real + os.sep):
        return None
    return candidate


def _apply_proposed_files(root: str, proposed_files: list[dict]) -> str | None:
    # Returns an error message on the first invalid path (nothing written for it, and
    # nothing after it is applied either); None on full success.
    for entry in proposed_files:
        file_path = entry.get("file_path")
        new_content = entry.get("new_content")
        if not isinstance(file_path, str) or not isinstance(new_content, str):
            return f"malformed proposed_files entry: {entry!r}"
        safe_path = _validate_relative_path(root, file_path)
        if safe_path is None:
            return f"rejected unsafe file_path: {file_path!r}"
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    return None


def _detect_stack(root: str) -> bool:
    has_manifest = os.path.exists(os.path.join(root, "requirements.txt")) or os.path.exists(os.path.join(root, "pyproject.toml"))
    if not has_manifest:
        return False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "node_modules", ".venv", "venv")]
        for name in filenames:
            if name.startswith("test_") and name.endswith(".py"):
                return True
            if name.endswith("_test.py"):
                return True
    return False


def _sandbox_user_ids() -> tuple[int, int] | None:
    try:
        import pwd  # POSIX-only -- absent on Windows, imported lazily so this module
        # itself stays importable there (local dev/tests), degrading gracefully instead.
        entry = pwd.getpwnam(SANDBOX_USER)
        return entry.pw_uid, entry.pw_gid
    except (ImportError, KeyError):
        # ImportError covers non-POSIX platforms; KeyError covers POSIX systems (e.g.
        # local dev outside the Docker image) where the dedicated sandbox user hasn't
        # been created -- degrade to a documented no-op rather than crash, the caller
        # falls back to running unprivileged-user-less.
        return None


def _chown_tree_to_sandbox_user(root: str) -> bool:
    ids = _sandbox_user_ids()
    if ids is None:
        return False
    uid, gid = ids
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            os.chown(dirpath, uid, gid)
            os.chmod(dirpath, 0o750)
            for name in filenames:
                path = os.path.join(dirpath, name)
                os.chown(path, uid, gid)
                os.chmod(path, 0o640)
        os.chown(root, uid, gid)
        return True
    except OSError:
        return False


def _scrubbed_env(home: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {key: os.environ[key] for key in _SAFE_ENV_ALLOWLIST if key in os.environ}
    env["HOME"] = home
    if extra:
        env.update(extra)
    return env


def _resource_limits_preexec(cpu_seconds: int, mem_bytes: int, nofile: int, unshare_net: bool):
    def _apply() -> None:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if unshare_net:
            try:
                os.unshare(os.CLONE_NEWNET)  # type: ignore[attr-defined]
            except (AttributeError, PermissionError, OSError):
                pass  # best-effort -- the caller separately probes whether this actually worked

    return _apply


def _sandbox_subprocess_kwargs(root: str, unshare_net: bool, uses_sandbox_user: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "cwd": root,
        "env": _scrubbed_env(home=root),
        "capture_output": True,
        "text": True,
        "preexec_fn": _resource_limits_preexec(cpu_seconds=90, mem_bytes=1024 * 1024 * 1024, nofile=256, unshare_net=unshare_net),
    }
    if uses_sandbox_user:
        kwargs["user"] = SANDBOX_USER
        kwargs["group"] = SANDBOX_USER
    return kwargs


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n... (truncated)"


def _run_phase1_install(root: str, timeout_seconds: int, uses_sandbox_user: bool) -> tuple[bool, str | None]:
    requirements_path = os.path.join(root, "requirements.txt")
    if not os.path.exists(requirements_path):
        return True, None
    kwargs = _sandbox_subprocess_kwargs(root, unshare_net=False, uses_sandbox_user=uses_sandbox_user)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", "requirements.txt"],
            timeout=timeout_seconds, **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        return False, _truncate(f"dependency install timed out after {timeout_seconds}s\n{exc.stdout or ''}{exc.stderr or ''}")
    except Exception as exc:
        return False, _truncate(f"{type(exc).__name__}: {exc}")
    output = _truncate((result.stdout or "") + (result.stderr or ""))
    return result.returncode == 0, output


def _network_is_isolated(root: str, uses_sandbox_user: bool) -> bool:
    # Verifies os.unshare(CLONE_NEWNET) actually took effect, rather than trusting its
    # own return value -- a real egress attempt from inside the same sandboxed
    # subprocess shape, immediately before the real test run.
    probe = "import socket; socket.setdefaulttimeout(2); socket.create_connection(('8.8.8.8', 53))"
    kwargs = _sandbox_subprocess_kwargs(root, unshare_net=True, uses_sandbox_user=uses_sandbox_user)
    try:
        result = subprocess.run([sys.executable, "-c", probe], timeout=5, **kwargs)
    except subprocess.TimeoutExpired:
        return True  # the connection attempt itself never completed -- isolated
    except Exception:
        return True
    return result.returncode != 0


def _run_phase2_pytest(root: str, timeout_seconds: int, uses_sandbox_user: bool) -> tuple[str, str, bool]:
    network_isolated = _network_is_isolated(root, uses_sandbox_user)
    kwargs = _sandbox_subprocess_kwargs(root, unshare_net=True, uses_sandbox_user=uses_sandbox_user)
    try:
        result = subprocess.run([sys.executable, "-m", "pytest", "-q"], timeout=timeout_seconds, **kwargs)
    except subprocess.TimeoutExpired as exc:
        return "error", _truncate(f"test run timed out after {timeout_seconds}s\n{exc.stdout or ''}{exc.stderr or ''}"), network_isolated
    except Exception as exc:
        return "error", _truncate(f"{type(exc).__name__}: {exc}"), network_isolated
    output = _truncate((result.stdout or "") + (result.stderr or ""))
    status = "passed" if result.returncode == 0 else "failed"
    return status, output, network_isolated


def _materialize_repo(owner: str, repo: str) -> str | None:
    dest_dir = tempfile.mkdtemp(prefix="voltsandbox-")
    root = github_tools.download_repo_tarball(owner, repo, dest_dir)
    if root is None:
        shutil.rmtree(dest_dir, ignore_errors=True)
        return None
    return root


def run_sandboxed_fix(owner: str, repo: str, proposed_files: list[dict], timeout_seconds: int = 120) -> dict:
    ran_at = datetime.now(timezone.utc).isoformat()
    root = _materialize_repo(owner, repo)
    if root is None:
        return {"status": "error", "output": "could not materialize repository", "install_output": None, "network_isolated": False, "ran_at": ran_at}

    sandbox_root = os.path.dirname(root)  # the tempdir _materialize_repo created, cleaned up as a whole
    try:
        try:
            apply_error = _apply_proposed_files(root, proposed_files)
            if apply_error is not None:
                return {"status": "error", "output": apply_error, "install_output": None, "network_isolated": False, "ran_at": ran_at}

            if not _detect_stack(root):
                return {"status": "unsupported_stack", "output": "no recognizable Python+pytest project (requirements.txt/pyproject.toml + test files)", "install_output": None, "network_isolated": False, "ran_at": ran_at}

            uses_sandbox_user = _chown_tree_to_sandbox_user(root)

            install_ok, install_output = _run_phase1_install(root, timeout_seconds, uses_sandbox_user)
            if not install_ok:
                return {"status": "error", "output": "dependency install failed", "install_output": install_output, "network_isolated": False, "ran_at": ran_at}

            status, output, network_isolated = _run_phase2_pytest(root, timeout_seconds, uses_sandbox_user)
            return {"status": status, "output": output, "install_output": install_output, "network_isolated": network_isolated, "ran_at": ran_at}
        except Exception as exc:
            # Never propagate -- one sandbox failure must never abort the whole
            # investigation (the diagnosis itself may still be perfectly valid).
            return {"status": "error", "output": f"{type(exc).__name__}: {exc}"[:MAX_OUTPUT_CHARS], "install_output": None, "network_isolated": False, "ran_at": ran_at}
    finally:
        shutil.rmtree(sandbox_root, ignore_errors=True)
