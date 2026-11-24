from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from sqlalchemy import func, select

from ..db import session_scope
from ..models import AuditRecord, KBEntryRecord, ProjectHealthRecord, ProjectRecord
from . import github_tools, knowledge_base

# One steward per project (identity "project:<key>"), deterministic, no LLM. Three levels:
#   Project Steward (this module's run_project_steward)
#     |- repo_health_checker   staleness, open PRs, CI
#     |- exposure_checker      repo visibility vs what the project is expected to be
#     |- kb_sync               pulls README/docs into the shared knowledge base
# It only READS from GitHub (GET requests through github_tools._github_request) and only
# WRITES to its own tables and the knowledge base.

DEFAULT_PROJECTS = [
    # key, name, kind, repo, repo_confirmed, deploy_url, notes
    ("volt-core", "Volt Core", "product", "moraisfrancisco1-blip/volt-core", True, "https://volt-core.vercel.app", "Centro de operações de agentes (este sistema)."),
    ("voltarisos", "VoltarisOS", "product", "moraisfrancisco1-blip/VoltarisOS", True, "https://voltarisos.com", "Plataforma de gestão de energia."),
    ("voltarisos-landing", "VoltarisOS landing", "product", "moraisfrancisco1-blip/voltarisos-landing", True, None, "Landing page do VoltarisOS."),
    ("dai-oakes-admin", "Studio Dai Oakes: painel admin", "client_site", "moraisfrancisco1-blip/daianeadminpanel-1688", True, "https://admin.studiodaioakes.com", "Painel admin da clínica."),
    ("dai-oakes-site", "Studio Dai Oakes: site", "client_site", None, False, "https://daianeoakes.com", "Repositório do site público por associar."),
    ("brievo", "Brievo", "product", "moraisfrancisco1-blip/brievo", True, None, "App que explica cartas oficiais neerlandesas (Play Store)."),
    ("mesa-de-funding", "Mesa de Funding", "product", None, False, "https://trading-sable-iota.vercel.app", "Mesa em papel de funding perpétuo vs spot. Repositório por associar."),
    ("kikomarketpredictor", "Kikomarketpredictor", "experiment", "moraisfrancisco1-blip/Kikomarketpredictor-4328", True, None, "Relação com a Mesa de Funding por confirmar."),
    ("volt-sandbox-verify", "Volt sandbox verify", "tool", "moraisfrancisco1-blip/volt-sandbox-verify", True, None, "Repositório de verificação da sandbox."),
]


def seed_default_projects() -> dict:
    created = 0
    with session_scope() as session:
        for key, name, kind, repo, confirmed, url, notes in DEFAULT_PROJECTS:
            if session.scalar(select(ProjectRecord.id).where(ProjectRecord.key == key)) is None:
                session.add(ProjectRecord(key=key, name=name, kind=kind, repo=repo, repo_confirmed=confirmed, deploy_url=url, notes=notes))
                created += 1
    return {"created": created, "already_present": len(DEFAULT_PROJECTS) - created}


def _stale_days() -> int:
    try:
        return max(1, int(os.getenv("VOLT_PROJECT_STALE_DAYS", "30")))
    except ValueError:
        return 30


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _get(path: str, **kw):
    return github_tools._github_request("GET", path, **kw)


# ---- L3: repo_health_checker
def repo_health_checker(repo: str, *, now: datetime) -> dict:
    meta = _get(f"/repos/{repo}")
    if meta is None:
        return {"error": "GitHub request failed (network)"}
    if meta.status_code != 200:
        return {"error": f"repo not reachable (status {meta.status_code}); private or missing, or GITHUB_TOKEN lacks access"}
    info = meta.json()
    branch = info.get("default_branch") or "main"
    pushed = _parse_ts(info.get("pushed_at"))
    out: dict = {"is_public": info.get("private") is False, "pushed_at": pushed, "branch": branch,
                 "days_since_push": round((now - pushed).total_seconds() / 86400, 1) if pushed else None, "open_prs": None, "oldest_pr_days": None, "ci_state": "unknown"}
    prs = _get(f"/repos/{repo}/pulls", params={"state": "open", "per_page": 100})
    if prs is not None and prs.status_code == 200:
        items = prs.json()
        out["open_prs"] = len(items)
        ages = [(now - t).total_seconds() / 86400 for t in (_parse_ts(i.get("created_at")) for i in items) if t]
        out["oldest_pr_days"] = round(max(ages), 1) if ages else None
    checks = _get(f"/repos/{repo}/commits/{branch}/check-runs", params={"per_page": 100})
    if checks is not None and checks.status_code == 200:
        runs = checks.json().get("check_runs", [])
        conclusions = {r.get("conclusion") for r in runs if r.get("status") == "completed"}
        if not runs:
            out["ci_state"] = "none"
        elif conclusions & {"failure", "timed_out", "cancelled", "action_required"}:
            out["ci_state"] = "failing"
        elif any(r.get("status") != "completed" for r in runs):
            out["ci_state"] = "pending"
        else:
            out["ci_state"] = "passing"
    return out


# ---- L3: exposure_checker
def exposure_checker(project: ProjectRecord, health: dict) -> list[str]:
    if health.get("is_public") and not project.expect_public:
        return ["public_repo_unexpected"]
    return []


# ---- L3: kb_sync
_DOC_PATH = re.compile(r"^(README\.md|CLAUDE\.md|AGENTS\.md|docs/[^/]+\.md)$")
MAX_SYNC_FILES = 12


def kb_sync(project_key: str, repo: str, branch: str) -> dict:
    tree = _get(f"/repos/{repo}/git/trees/{branch}", params={"recursive": "1"})
    if tree is None or tree.status_code != 200:
        return {"error": "could not list repository tree", "created": 0, "updated": 0, "unchanged": 0, "refused": 0}
    result = {"created": 0, "updated": 0, "unchanged": 0, "refused": 0, "error": None}
    docs = [i for i in tree.json().get("tree", []) if i.get("type") == "blob" and _DOC_PATH.match(i["path"])
            and not github_tools._is_noise(i["path"]) and not github_tools._is_sensitive(i["path"])][:MAX_SYNC_FILES]
    for item in docs:
        source, sha = f"repo:{item['path']}", item.get("sha") or ""
        with session_scope() as session:
            existing = session.scalar(select(KBEntryRecord).where(KBEntryRecord.project_key == project_key, KBEntryRecord.source == source))
            if existing is not None and existing.source_sha == sha and existing.status == "active":
                result["unchanged"] += 1
                continue
        resp = _get(f"/repos/{repo}/contents/{item['path']}", headers={"Accept": "application/vnd.github.raw+json"})
        if resp is None or resp.status_code != 200:
            continue
        try:
            outcome = knowledge_base.upsert_synced(project_key=project_key, source=source, source_sha=sha, title=f"{project_key}: {item['path']}", body=resp.text[:knowledge_base.MAX_BODY_CHARS])
            result[outcome] += 1
        except knowledge_base.KBRefused as exc:
            result["refused"] += 1
            with session_scope() as session:
                session.add(AuditRecord(type="kb_sync_refused", reference_id=project_key, detail=f"{item['path']}: {exc}"[:500]))
    return result


# ---- L2: the steward
def run_project_steward(project_key: str, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    with session_scope() as session:
        project = session.scalar(select(ProjectRecord).where(ProjectRecord.key == project_key))
        if project is None:
            return {"ran": False, "reason": "unknown project"}
        session.expunge(project)
        kb_count = session.scalar(select(func.count()).select_from(KBEntryRecord).where(KBEntryRecord.project_key == project_key, KBEntryRecord.status == "active")) or 0

    flags: list[str] = []
    health: dict = {}
    sync: dict | None = None
    error: str | None = None
    if not project.repo:
        flags.append("no_repo")
    else:
        health = repo_health_checker(project.repo, now=now)
        if "error" in health:
            error = health["error"]
            flags.append("repo_unreachable")
        else:
            flags += exposure_checker(project, health)
            if (health.get("days_since_push") or 0) > _stale_days():
                flags.append("stale_repo")
            if (health.get("oldest_pr_days") or 0) > 7:
                flags.append("stale_prs")
            if health.get("ci_state") == "failing":
                flags.append("ci_failing")
            sync = kb_sync(project_key, project.repo, health["branch"])
            if sync["refused"]:
                flags.append("kb_secret_refused")
            kb_count += sync["created"]
    if kb_count == 0:
        flags.append("kb_empty")
    if not project.repo_confirmed and project.repo:
        flags.append("repo_unconfirmed")

    with session_scope() as session:
        session.add(ProjectHealthRecord(project_key=project_key, pushed_at=health.get("pushed_at"), days_since_push=health.get("days_since_push"),
                                        open_prs=health.get("open_prs"), oldest_pr_days=health.get("oldest_pr_days"), ci_state=health.get("ci_state"),
                                        is_public=health.get("is_public"), flags=flags, error=error))
        session.add(AuditRecord(type="project_steward_completed", reference_id=project_key, detail=f"flags={','.join(flags) or 'none'}"))
    return {"ran": True, "project": project_key, "flags": flags, "kb_sync": sync, "error": error}


# Flags that deserve the owner's attention in the daily briefing. The rest are informational.
ATTENTION_FLAGS = {"public_repo_unexpected", "ci_failing", "repo_unreachable", "stale_prs", "kb_secret_refused"}


def latest_health_by_project() -> list[dict]:
    with session_scope() as session:
        projects = session.scalars(select(ProjectRecord).where(ProjectRecord.status == "active").order_by(ProjectRecord.key)).all()
        out = []
        for p in projects:
            h = session.scalar(select(ProjectHealthRecord).where(ProjectHealthRecord.project_key == p.key).order_by(ProjectHealthRecord.id.desc()))
            kb = session.scalar(select(func.count()).select_from(KBEntryRecord).where(KBEntryRecord.project_key == p.key, KBEntryRecord.status == "active")) or 0
            out.append({"key": p.key, "name": p.name, "repo": p.repo, "kb_entries": kb, "flags": (h.flags if h else None) or [], "checked": h is not None,
                        "days_since_push": h.days_since_push if h else None, "open_prs": h.open_prs if h else None, "ci_state": h.ci_state if h else None,
                        "checked_at": h.created_at.isoformat() if h and h.created_at else None})
        return out
