from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import session_scope
from ..models import KBEntryRecord, ProjectHealthRecord, ProjectRecord
from . import knowledge_base, project_agent

router = APIRouter(prefix="/api", tags=["knowledge-and-projects"])


class KBEntryIn(BaseModel):
    title: str = Field(max_length=200)
    body: str
    project_key: str | None = None
    tags: list[str] = []


class ProjectIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    name: str
    kind: str = "product"
    status: str = "active"
    repo: str | None = Field(default=None, pattern=r"^[\w.-]+/[\w.-]+$")
    repo_confirmed: bool = False
    deploy_url: str | None = None
    expect_public: bool = False
    notes: str | None = None


def project_dict(p: ProjectRecord) -> dict:
    return {"key": p.key, "name": p.name, "kind": p.kind, "status": p.status, "repo": p.repo, "repo_confirmed": p.repo_confirmed,
            "deploy_url": p.deploy_url, "expect_public": p.expect_public, "notes": p.notes}


@router.get("/projects")
def list_projects() -> list[dict]:
    with session_scope() as session:
        return [project_dict(p) for p in session.scalars(select(ProjectRecord).order_by(ProjectRecord.key)).all()]


@router.post("/projects")
def upsert_project(body: ProjectIn) -> dict:
    if body.kind not in {"product", "client_site", "tool", "experiment"} or body.status not in {"active", "paused"}:
        raise HTTPException(status_code=422, detail="invalid kind or status")
    with session_scope() as session:
        p = session.scalar(select(ProjectRecord).where(ProjectRecord.key == body.key))
        if p is None:
            p = ProjectRecord(key=body.key, name=body.name)
            session.add(p)
        for field, value in body.model_dump().items():
            setattr(p, field, value)
        session.flush()
        return project_dict(p)


@router.post("/projects/seed-defaults")
def seed_defaults() -> dict:
    # Explicit, never automatic: some default repo mappings are unconfirmed (repo_confirmed=false).
    return project_agent.seed_default_projects()


@router.post("/projects/{key}/steward/run")
def run_steward(key: str) -> dict:
    result = project_agent.run_project_steward(key)
    if not result["ran"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result


@router.get("/projects/{key}/health")
def project_health(key: str, limit: int = Query(default=10, ge=1, le=100)) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(select(ProjectHealthRecord).where(ProjectHealthRecord.project_key == key).order_by(ProjectHealthRecord.id.desc()).limit(limit)).all()
        return [{"id": r.id, "days_since_push": r.days_since_push, "open_prs": r.open_prs, "oldest_pr_days": r.oldest_pr_days, "ci_state": r.ci_state,
                 "is_public": r.is_public, "flags": r.flags or [], "error": r.error, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


@router.get("/kb/search")
def kb_search(q: str = Query(min_length=2), project: str | None = None, limit: int = Query(default=5, ge=1, le=20)) -> list[dict]:
    return knowledge_base.search(q, project_key=project, limit=limit)


@router.get("/kb/entries")
def kb_entries(project: str | None = None, status: str = "active", limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    if status not in {"active", "archived"}:
        raise HTTPException(status_code=422, detail="invalid status")
    with session_scope() as session:
        stmt = select(KBEntryRecord).where(KBEntryRecord.status == status)
        if project:
            stmt = stmt.where(KBEntryRecord.project_key == project)
        return [knowledge_base.entry_dict(r) for r in session.scalars(stmt.order_by(KBEntryRecord.id.desc()).limit(limit)).all()]


@router.post("/kb/entries")
def kb_add(body: KBEntryIn) -> dict:
    try:
        return knowledge_base.add_entry(title=body.title, body=body.body, project_key=body.project_key, tags=body.tags)
    except knowledge_base.KBRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/kb/entries/{entry_id}/archive")
def kb_archive(entry_id: int) -> dict:
    if not knowledge_base.archive_entry(entry_id):
        raise HTTPException(status_code=404, detail="entry not found")
    return {"id": entry_id, "status": "archived"}
