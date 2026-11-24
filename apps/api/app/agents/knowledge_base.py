from __future__ import annotations

import re

from sqlalchemy import select

from ..db import session_scope
from ..models import KBEntryRecord
from . import output_auditor

# Shared knowledge base. project_key=None means "shared by every project and agent".
# Two guarantees, both structural:
#   1. Nothing with a secret pattern is ever stored (output_auditor.secret_checker runs on
#      every write, manual or synced). The refusal names the rule, never the match.
#   2. Search is plain term-scoring over stored text: no LLM, no embeddings, no network.
MAX_BODY_CHARS = 20_000
_SEARCH_POOL = 2000


class KBRefused(ValueError):
    """Raised when content is refused (secret detected, empty, too large)."""


def _check(title: str, body: str) -> None:
    if not title.strip() or not body.strip():
        raise KBRefused("title and body are required")
    if len(body) > MAX_BODY_CHARS:
        raise KBRefused(f"body too large (max {MAX_BODY_CHARS} chars)")
    rules = [f["rule"] for f in output_auditor.secret_checker(f"{title}\n{body}")]
    if rules:
        raise KBRefused("refused: possible secret detected (" + ", ".join(rules) + "); nothing was stored")


def entry_dict(row: KBEntryRecord, *, snippet: str | None = None, score: int | None = None) -> dict:
    out = {"id": row.id, "project_key": row.project_key, "title": row.title, "tags": row.tags or [], "source": row.source, "status": row.status,
           "updated_at": row.updated_at.isoformat() if row.updated_at else None}
    out["snippet" if snippet is not None else "body"] = snippet if snippet is not None else row.body
    if score is not None:
        out["score"] = score
    return out


def add_entry(*, title: str, body: str, project_key: str | None = None, tags: list[str] | None = None) -> dict:
    _check(title, body)
    with session_scope() as session:
        row = KBEntryRecord(project_key=project_key, title=title.strip()[:200], body=body, tags=[str(t)[:40] for t in (tags or [])][:12])
        session.add(row)
        session.flush()
        return entry_dict(row)


def upsert_synced(*, project_key: str, source: str, source_sha: str, title: str, body: str) -> str:
    """Idempotent write for repo-synced docs. Returns 'created' | 'updated' | 'unchanged'.
    Raises KBRefused if the content holds a secret (existing entry is left untouched)."""
    _check(title, body)
    with session_scope() as session:
        row = session.scalar(select(KBEntryRecord).where(KBEntryRecord.project_key == project_key, KBEntryRecord.source == source))
        if row is None:
            session.add(KBEntryRecord(project_key=project_key, source=source, source_sha=source_sha, title=title[:200], body=body, tags=["repo-doc"]))
            return "created"
        if row.source_sha == source_sha and row.status == "active":
            return "unchanged"
        row.source_sha, row.title, row.body, row.status = source_sha, title[:200], body, "active"
        return "updated"


def archive_entry(entry_id: int) -> bool:
    with session_scope() as session:
        row = session.get(KBEntryRecord, entry_id)
        if row is None:
            return False
        row.status = "archived"
        return True


def search(query: str, *, project_key: str | None = None, limit: int = 5) -> list[dict]:
    terms = {t for t in re.findall(r"\w{3,}", query.lower())}
    if not terms:
        return []
    with session_scope() as session:
        stmt = select(KBEntryRecord).where(KBEntryRecord.status == "active")
        if project_key is not None:
            stmt = stmt.where((KBEntryRecord.project_key == project_key) | (KBEntryRecord.project_key.is_(None)))
        rows = session.scalars(stmt.order_by(KBEntryRecord.id.desc()).limit(_SEARCH_POOL)).all()
        scored = []
        for row in rows:
            title, body, tags = row.title.lower(), row.body.lower(), " ".join(row.tags or []).lower()
            score = sum(3 * title.count(t) + body.count(t) + 2 * tags.count(t) for t in terms)
            if score:
                first = min((body.find(t) for t in terms if t in body), default=-1)
                start = max(0, first - 80) if first >= 0 else 0
                scored.append((score, row, row.body[start:start + 300]))
        scored.sort(key=lambda x: -x[0])
        return [entry_dict(row, snippet=snip, score=score) for score, row, snip in scored[:limit]]


def context_for(project_key: str | None, query: str, *, limit: int = 3) -> str:
    # What any agent can paste into its own context: project entries first-class, shared
    # entries included. Empty string when nothing matches, so callers can add it blindly.
    hits = search(query, project_key=project_key, limit=limit)
    return "\n\n".join(f"[{h['title']}]\n{h['snippet']}" for h in hits)
