from __future__ import annotations

import re

from sqlalchemy import select

from ..db import session_scope
from ..models import AuditRecord, OutputAuditFindingRecord
from .approvals_rollup import SOURCES

# Output Auditor: a parent agent with two deterministic sub-checkers that run over every
# pending draft before a human sees it.
#   - secret_checker: an agent that echoes a key/token/password into a draft is a critical
#     incident (this repo has had plain-text secret incidents before).
#   - content_checker: things a human should double-check even though no rule is "wrong":
#     prices, IBANs/phones, and absolute or medical-sounding claims.
# No LLM, no network. It NEVER stores the matched text for secret/PII rules, only the rule
# name, so the audit trail cannot itself leak what it flags.

_SECRET_RULES = [
    ("secret_api_key", re.compile(r"\b(?:sk|rk|pk)[-_][A-Za-z0-9_-]{20,}")),
    ("secret_github_token", re.compile(r"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}")),
    ("secret_aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("secret_resend_key", re.compile(r"\bre_[A-Za-z0-9]{20,}")),
    ("secret_private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("secret_assignment", re.compile(r"(?i)\b(?:password|passwort|wachtwoord|senha|secret|api[_-]?key|auth[_-]?token)\b\s*[:=]\s*\S{8,}")),
]
_PRICE = re.compile(r"(€\s?\d[\d.,]*|\b\d[\d.,]*\s?(?:€|eur\b|euro\b))", re.IGNORECASE)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b")
_PHONE = re.compile(r"(?<!\d)\+\d[\d\s-]{8,14}\d")
_ABSOLUTE = re.compile(r"(?i)\b(?:garantid[oa]s?|garantimos|guarantee[sd]?|garandeer\w*|100\s?%|cura\w*|curamos|cure[sd]?|genez\w+)\b")


def secret_checker(text: str) -> list[dict]:
    return [{"rule": name, "severity": "critical", "excerpt": "[redacted]"} for name, rx in _SECRET_RULES if rx.search(text)]


def content_checker(text: str) -> list[dict]:
    findings: list[dict] = []
    if (m := _PRICE.search(text)):
        findings.append({"rule": "price_mentioned", "severity": "attention", "excerpt": m.group(0)[:60]})
    if _IBAN.search(text):
        findings.append({"rule": "iban_present", "severity": "critical", "excerpt": "[redacted]"})
    if _PHONE.search(text):
        findings.append({"rule": "phone_present", "severity": "attention", "excerpt": "[redacted]"})
    if (m := _ABSOLUTE.search(text)):
        findings.append({"rule": "absolute_claim", "severity": "attention", "excerpt": m.group(0)[:60]})
    return findings


def scan_text(text: str) -> list[dict]:
    return secret_checker(text or "") + content_checker(text or "")


def _draft_text(row) -> str:
    return " \n".join(str(getattr(row, field, "") or "") for field in ("subject", "title", "body", "price_summary", "description"))


def run_output_audit() -> dict:
    new_findings = 0
    scanned = 0
    with session_scope() as session:
        for source, model, _ in SOURCES:
            for row in session.scalars(select(model).where(model.status == "pending_approval")).all():
                scanned += 1
                for finding in scan_text(_draft_text(row)):
                    exists = session.scalar(select(OutputAuditFindingRecord.id).where(
                        OutputAuditFindingRecord.source == source, OutputAuditFindingRecord.source_id == row.id,
                        OutputAuditFindingRecord.rule == finding["rule"]))
                    if exists is None:
                        session.add(OutputAuditFindingRecord(source=source, source_id=row.id, **finding))
                        new_findings += 1
        session.add(AuditRecord(type="output_audit_completed", detail=f"scanned={scanned} new_findings={new_findings}"))
    with session_scope() as session:
        open_rows = session.scalars(select(OutputAuditFindingRecord).where(OutputAuditFindingRecord.status == "open")).all()
        critical = sum(1 for r in open_rows if r.severity == "critical")
        return {"scanned": scanned, "new_findings": new_findings, "open": len(open_rows), "open_critical": critical}
