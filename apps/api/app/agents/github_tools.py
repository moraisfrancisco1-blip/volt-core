from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from ..db import session_scope
from ..models import AgentInvestigationRecord

_API_BASE = "https://api.github.com"


@dataclass(frozen=True)
class CodeDiagnosisJob:
    event_id: int
    escalation_id: int
    system: str
    environment: str
    priority: str
    owner: str
    repo: str
    parent_investigation_id: int


def _github_request(method: str, path: str, **kwargs) -> httpx.Response | None:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    # Returns None only on a transport-level failure (DNS/timeout/connection refused);
    # HTTP error statuses (403/404/...) come back as a normal Response for callers to
    # interpret, same as any other GitHub error.
    token = os.getenv("GITHUB_TOKEN")
    headers = {"X-GitHub-Api-Version": "2022-11-28", **kwargs.pop("headers", {})}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(base_url=_API_BASE, timeout=15) as client:
            return client.request(method, path, headers=headers, **kwargs)
    except httpx.HTTPError:
        return None


# Exact segment-name matching, not "substring contained in segment" -- a substring check
# would wrongly exclude real files like electron-builder.json5 (contains "build") that
# genuinely exist in these repos.
_NOISE_SEGMENTS = {
    "node_modules", ".next", "dist", "build", ".npm-cache", "_cacache",
    "__pycache__", ".git", ".venv", "venv", ".turbo", ".cache",
    "coverage", "vendor", "target", ".pytest_cache", "site-packages",
}
_NOISE_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock",
    "poetry.lock", "Cargo.lock", "uv.lock",
}


def _is_noise(path: str) -> bool:
    segments = path.split("/")
    if any(segment in _NOISE_SEGMENTS for segment in segments):
        return True
    return segments[-1] in _NOISE_FILENAMES


# Refuses before any network call. Even though this only ever reads the user's own
# repos, the content becomes LLM context sent to the Anthropic API -- this is a technical
# floor, not something left to discipline alone.
_DENY_PATTERNS = [
    re.compile(r"(^|/)\.env(\.|$)"),
    re.compile(r"\.pem$"),
    re.compile(r"\.key$"),
    re.compile(r"id_rsa"),
    re.compile(r"secret", re.I),
    re.compile(r"credential", re.I),
]
_ALLOWED_ENV_SUFFIXES = (".example", ".template")


def _is_sensitive(path: str) -> bool:
    if path.lower().endswith(_ALLOWED_ENV_SUFFIXES):
        return False
    return any(pattern.search(path) for pattern in _DENY_PATTERNS)


def _default_branch(owner: str, repo: str) -> str | None:
    response = _github_request("GET", f"/repos/{owner}/{repo}")
    if response is None or response.status_code != 200:
        return None
    return response.json().get("default_branch")


def list_repo_files(job: CodeDiagnosisJob, path: str = "") -> dict:
    branch = _default_branch(job.owner, job.repo)
    if branch is None:
        return {"error": "could not resolve default branch"}
    response = _github_request("GET", f"/repos/{job.owner}/{job.repo}/git/trees/{branch}", params={"recursive": "1"})
    if response is None or response.status_code != 200:
        return {"error": f"GitHub API request failed (status={getattr(response, 'status_code', 'n/a')})"}
    payload = response.json()
    prefix = path.strip("/")
    files = [
        item["path"]
        for item in payload.get("tree", [])
        if item.get("type") == "blob"
        and (not prefix or item["path"] == prefix or item["path"].startswith(prefix + "/"))
        and not _is_noise(item["path"])
    ]
    files.sort()
    return {
        "path": prefix or "/",
        "file_count": len(files),
        "files": files[:500],
        "listing_truncated_by_tool": len(files) > 500,
        # The repo tree itself exceeded GitHub's own response limit, before our filter ran.
        "listing_truncated_by_github": bool(payload.get("truncated")),
    }


MAX_FILE_CHARS = 40_000  # keeps one file read from blowing the per-turn token budget


def read_repo_file(job: CodeDiagnosisJob, path: str) -> dict:
    if _is_sensitive(path):
        return {"path": path, "refused": True, "reason": "refused: sensitive file pattern"}
    response = _github_request(
        "GET", f"/repos/{job.owner}/{job.repo}/contents/{path}",
        headers={"Accept": "application/vnd.github.raw+json"},
    )
    if response is None:
        return {"error": "GitHub API request failed (network/transport error)"}
    if response.status_code == 404:
        return {"error": f"{path} not found in {job.owner}/{job.repo}"}
    if response.status_code != 200:
        return {"error": f"GitHub API returned {response.status_code}"}
    if "application/json" in response.headers.get("content-type", ""):
        return {"error": f"{path} is a directory -- use list_repo_files instead"}
    content = response.text
    return {
        "path": path,
        "content": content[:MAX_FILE_CHARS],
        "truncated": len(content) > MAX_FILE_CHARS,
        "total_chars": len(content),
    }


def search_repo_code(job: CodeDiagnosisJob, query: str) -> dict:
    response = _github_request(
        "GET", "/search/code",
        params={"q": f"{query} repo:{job.owner}/{job.repo}", "per_page": 20},
        headers={"Accept": "application/vnd.github.text-match+json"},
    )
    if response is None:
        return {"error": "GitHub API request failed (network/transport error)"}
    if response.status_code == 403:
        return {"error": "GitHub code search rate limit hit -- try list_repo_files/read_repo_file instead"}
    if response.status_code != 200:
        return {"error": f"GitHub API returned {response.status_code}"}
    payload = response.json()
    items = [
        {
            "path": item["path"],
            "fragments": [tm.get("fragment", "") for tm in item.get("text_matches", []) if tm.get("fragment")][:3],
        }
        for item in payload.get("items", [])
        if not _is_noise(item.get("path", ""))
    ]
    return {"total_count": payload.get("total_count", 0), "items": items[:20]}


def get_recent_commits(job: CodeDiagnosisJob, path: str = "", limit: int = 10) -> dict:
    limit = max(1, min(int(limit), 30))
    params = {"per_page": limit, **({"path": path} if path else {})}
    response = _github_request("GET", f"/repos/{job.owner}/{job.repo}/commits", params=params)
    if response is None:
        return {"error": "GitHub API request failed (network/transport error)"}
    if response.status_code != 200:
        return {"error": f"GitHub API returned {response.status_code}"}
    return {
        "commits": [
            {
                "sha": item.get("sha", "")[:12],
                "author": (item.get("commit", {}).get("author") or {}).get("name"),
                "date": (item.get("commit", {}).get("author") or {}).get("date"),
                "message": (item.get("commit", {}).get("message") or "").splitlines()[0][:200] if item.get("commit", {}).get("message") else "",
            }
            for item in response.json()
        ]
    }


def get_prior_investigation(job: CodeDiagnosisJob) -> dict:
    with session_scope() as session:
        record = session.get(AgentInvestigationRecord, job.parent_investigation_id)
        if record is None:
            return {"error": "prior investigation not found"}
        return {
            "id": record.id,
            "status": record.status,
            "hypothesis": record.hypothesis,
            "recommended_next_step": record.recommended_next_step,
            "confidence": record.confidence,
            "is_known_pattern": record.is_known_pattern,
        }


TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "list_repo_files": list_repo_files,
    "read_repo_file": read_repo_file,
    "search_repo_code": search_repo_code,
    "get_recent_commits": get_recent_commits,
    "get_prior_investigation": get_prior_investigation,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_repo_files",
        "description": "List files in the repository (recursively), optionally scoped to a subdirectory. Build-artifact noise (node_modules, dist, .next, lockfiles, caches, etc.) is filtered out automatically. On a large repository, prefer scoping `path` to a specific subdirectory rather than listing everything.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Subdirectory to scope the listing to (default: whole repo)."}},
            "required": [],
        },
    },
    {
        "name": "read_repo_file",
        "description": "Read the contents of one file from the repository, given its full path. Refuses files matching a sensitive-data pattern (.env, keys, secrets, credentials).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Full path to the file, as returned by list_repo_files or search_repo_code."}},
            "required": ["path"],
        },
    },
    {
        "name": "search_repo_code",
        "description": "Search the repository's code for a string or pattern, scoped to this repo only. Rate-limited more tightly than other GitHub API calls -- prefer list_repo_files/read_repo_file when you already have a good guess at the path.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query (plain text or GitHub code search syntax)."}},
            "required": ["query"],
        },
    },
    {
        "name": "get_recent_commits",
        "description": "Read recent commit history for the repository, optionally scoped to one file or directory -- useful to check whether a recent change correlates with the incident.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Optional file or directory path to scope the history to."},
                "limit": {"type": "integer", "description": "Max commits to return (default 10, max 30)."},
            },
            "required": [],
        },
    },
    {
        "name": "get_prior_investigation",
        "description": "Read the Production Monitor's earlier diagnosis of this same incident (hypothesis, recommended next step, confidence) -- start here so you're not investigating from scratch.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]
