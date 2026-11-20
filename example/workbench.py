"""Minimal proposal workbench that applies the verifiable-constitution template.

Decision records: docs/adr/0001-proposal-workbench.md, docs/adr/0002-agent-evaluation-gate.md

An agent (or a deterministic rule) proposes who should take a pending work item; nothing happens
until a qualified human approves. Python standard library only (sqlite3), so the checks and the
planted violations can be reproduced anywhere.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

SCHEMA_SQL = """
CREATE TABLE users (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, role TEXT NOT NULL);
CREATE TABLE work_items (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, assignee_id TEXT);
CREATE TABLE proposals (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  proposer TEXT NOT NULL CHECK (proposer IN ('RULE', 'AGENT')),
  target_id TEXT NOT NULL,
  evidence TEXT NOT NULL CHECK (json_valid(evidence) AND json_array_length(evidence) > 0),
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
  decided_by TEXT
);
CREATE TRIGGER proposals_evidence_items BEFORE INSERT ON proposals
  WHEN CASE WHEN json_valid(NEW.evidence) AND json_type(NEW.evidence) = 'array' THEN EXISTS (
      SELECT 1 FROM json_each(NEW.evidence) e
      WHERE e.type IS NOT 'object'
         OR json_type(e.value, '$.code') IS NOT 'text'
         OR json_extract(e.value, '$.code') NOT GLOB '[A-Z]*'
         OR json_extract(e.value, '$.code') GLOB '*[^A-Z0-9_]*'
         OR coalesce(json_type(e.value, '$.value'), '') NOT IN ('text', 'integer', 'real')
         OR (json_type(e.value, '$.value') = 'text' AND trim(json_extract(e.value, '$.value'), ' ' || char(9, 10, 11, 12, 13)) = ''))
    ELSE 0 END
  BEGIN SELECT RAISE(ABORT, 'evidence item without code or value'); END;
CREATE TRIGGER proposals_immutable_when_decided BEFORE UPDATE ON proposals
  WHEN OLD.status <> 'PENDING' BEGIN SELECT RAISE(ABORT, 'decided proposal is immutable'); END;
CREATE TRIGGER proposals_retained BEFORE DELETE ON proposals
  BEGIN SELECT RAISE(ABORT, 'proposal must be retained'); END;
CREATE TABLE audit_trail (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  actor_type TEXT NOT NULL CHECK (actor_type IN ('HUMAN', 'SYSTEM', 'AGENT')),
  actor_id TEXT NOT NULL,
  action TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  data TEXT NOT NULL
);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_trail BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_trail BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TABLE session_tenant (tenant_id TEXT NOT NULL);
CREATE VIEW v_users AS SELECT * FROM users WHERE tenant_id = (SELECT tenant_id FROM session_tenant);
CREATE VIEW v_proposals AS SELECT * FROM proposals WHERE tenant_id = (SELECT tenant_id FROM session_tenant);
CREATE VIEW v_work_items AS SELECT * FROM work_items WHERE tenant_id = (SELECT tenant_id FROM session_tenant);
CREATE TRIGGER proposals_same_tenant BEFORE INSERT ON proposals
  WHEN NEW.tenant_id IS NOT (SELECT tenant_id FROM session_tenant)
    OR NOT EXISTS (SELECT 1 FROM work_items WHERE id = NEW.item_id AND tenant_id = NEW.tenant_id)
    OR NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.target_id AND tenant_id = NEW.tenant_id)
  BEGIN SELECT RAISE(ABORT, 'proposal crosses tenants'); END;
CREATE TRIGGER proposals_inserted_pending BEFORE INSERT ON proposals
  WHEN NEW.status IS NOT 'PENDING' OR NEW.decided_by IS NOT NULL
  BEGIN SELECT RAISE(ABORT, 'a proposal is inserted pending; it is decided only by an update'); END;
CREATE TRIGGER proposals_content_fixed BEFORE UPDATE OF id, tenant_id, item_id, proposer, target_id, evidence ON proposals
  BEGIN SELECT RAISE(ABORT, 'proposal content cannot be rewritten'); END;
CREATE TRIGGER proposals_decided_in_tenant BEFORE UPDATE OF status, decided_by ON proposals
  WHEN OLD.tenant_id IS NOT (SELECT tenant_id FROM session_tenant)
    OR NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.decided_by AND tenant_id = OLD.tenant_id)
  BEGIN SELECT RAISE(ABORT, 'decision crosses tenants'); END;
CREATE TRIGGER work_items_inserted_in_tenant BEFORE INSERT ON work_items
  WHEN NEW.tenant_id IS NOT (SELECT tenant_id FROM session_tenant)
    OR (NEW.assignee_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.assignee_id AND tenant_id = NEW.tenant_id))
  BEGIN SELECT RAISE(ABORT, 'work item crosses tenants'); END;
CREATE TRIGGER work_items_same_tenant BEFORE UPDATE ON work_items
  WHEN OLD.tenant_id IS NOT (SELECT tenant_id FROM session_tenant)
    OR NEW.tenant_id IS NOT OLD.tenant_id
    OR (NEW.assignee_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.assignee_id AND tenant_id = OLD.tenant_id))
  BEGIN SELECT RAISE(ABORT, 'effect crosses tenants'); END;
CREATE TRIGGER work_items_id_fixed BEFORE UPDATE OF id ON work_items
  BEGIN SELECT RAISE(ABORT, 'work item id cannot change'); END;
CREATE TRIGGER work_items_deleted_in_tenant BEFORE DELETE ON work_items
  WHEN OLD.tenant_id IS NOT (SELECT tenant_id FROM session_tenant)
  BEGIN SELECT RAISE(ABORT, 'effect crosses tenants'); END;
CREATE TRIGGER work_items_retained_when_proposed BEFORE DELETE ON work_items
  WHEN EXISTS (SELECT 1 FROM proposals WHERE item_id = OLD.id)
  BEGIN SELECT RAISE(ABORT, 'work item has proposals'); END;
CREATE TRIGGER users_identity_fixed BEFORE UPDATE OF id, tenant_id ON users
  BEGIN SELECT RAISE(ABORT, 'user id and tenant cannot change'); END;
CREATE TRIGGER users_retained_when_referenced BEFORE DELETE ON users
  WHEN EXISTS (SELECT 1 FROM work_items WHERE assignee_id = OLD.id)
    OR EXISTS (SELECT 1 FROM proposals WHERE target_id = OLD.id OR decided_by = OLD.id)
  BEGIN SELECT RAISE(ABORT, 'user is referenced'); END;
"""
REASON_CODES = ("LEAST_LOAD", "SPECIALTY", "BALANCED")
CONFIDENCE_CODE = re.compile(r"(^|_)(CONFIDENCE|SCORE|PROBABILITY|CERTAINTY|LIKELIHOOD)(_|$)")
EVIDENCE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
APPROVER_ROLES = ("coordinator",)

PROMPT_HEADER = (
    "Choose which professional should take a pending work item.",
    'Answer ONLY with JSON: {"user_id": "<one id from the list>", "reason_code": "<LEAST_LOAD|SPECIALTY|BALANCED>"}',
)


def prompt_version(header: tuple[str, ...] = PROMPT_HEADER) -> str:
    return hashlib.sha256("\n".join(header).encode()).hexdigest()[:12]


@dataclass(frozen=True)
class AgentTask:
    task: str = "REASSIGN"
    model: str = "example/small-model"
    actor_id: str = "agent-reassign"

    @property
    def prompt_version(self) -> str:
        return prompt_version()


class EvidenceError(ValueError):
    """C3: proposal without traceable evidence."""


class AuthorizationError(PermissionError):
    """C4: approver not qualified to perform the effect directly."""


def connect(schema_sql: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    # REPLACE deletes the conflicting row; only with recursive triggers on does that deletion fire the
    # DELETE triggers, so INSERT OR REPLACE cannot rewrite or remove a guarded row (C5, C6, C7).
    conn.execute("PRAGMA recursive_triggers = ON")
    conn.executescript(schema_sql if schema_sql is not None else SCHEMA_SQL)
    return conn


def assert_evidence(evidence: list[dict]) -> None:
    if not isinstance(evidence, list) or not evidence:
        raise EvidenceError("empty evidence")
    for item in evidence:
        if not isinstance(item.get("code"), str) or not EVIDENCE_CODE.match(item["code"]):
            raise EvidenceError(f"invalid evidence code: {item.get('code')!r}")
        value = item.get("value")
        if not ((isinstance(value, str) and value.strip()) or (isinstance(value, (int, float)) and value == value)):
            raise EvidenceError(f"evidence {item['code']} has no value")
    if all(CONFIDENCE_CODE.search(item["code"]) for item in evidence):
        raise EvidenceError("confidence is not evidence")


def validate_choice(data: object, candidate_ids: list[str]) -> Optional[dict]:
    """C2 and C9: the answer must point inside the closed list; the reason must be a contract code."""
    if not isinstance(data, dict):
        return None
    raw = data.get("user_id")
    chosen = raw.strip().lower() if isinstance(raw, str) else ""
    canonical = next((c for c in candidate_ids if c.lower() == chosen), None)
    if canonical is None:
        return None
    reason = data.get("reason_code")
    return {"user_id": canonical, "reason_code": reason if reason in REASON_CODES else "UNSPECIFIED"}


def eval_approved(eval_file: Optional[Path], task: AgentTask) -> bool:
    """C8: the model is called only with an approved evaluation for this (model, prompt version)."""
    if eval_file is None or not Path(eval_file).is_file():
        return False
    result = json.loads(Path(eval_file).read_text())
    return (
        result.get("approved") is True
        and result.get("task") == task.task
        and result.get("model") == task.model
        and result.get("prompt_version") == task.prompt_version
    )


class Workbench:
    def __init__(self, conn: sqlite3.Connection, tenant_id: str,
                 runtime: Optional[Callable[[str], object]] = None,
                 eval_file: Optional[Path] = None, task: AgentTask = AgentTask()):
        self.conn, self.tenant_id, self.runtime, self.eval_file, self.task = conn, tenant_id, runtime, eval_file, task
        self.scope()

    def scope(self) -> None:
        """C6: the session tenant that the views and triggers check (emulates a row-level security setting)."""
        with self.conn:
            self.conn.execute("DELETE FROM session_tenant")
            self.conn.execute("INSERT INTO session_tenant VALUES (?)", (self.tenant_id,))

    # --- proposals -------------------------------------------------------------------------
    def candidates(self) -> list[tuple[str, int]]:
        self.scope()
        rows = self.conn.execute(
            "SELECT u.id, (SELECT count(*) FROM v_work_items w WHERE w.assignee_id = u.id) "
            "FROM v_users u WHERE u.role = 'professional' ORDER BY u.id")
        return [(r[0], r[1]) for r in rows]

    def ask_agent(self, candidates: list[tuple[str, int]]) -> Optional[dict]:
        if self.runtime is None or not eval_approved(self.eval_file, self.task):
            return None
        prompt = "\n".join(self.task_prompt(candidates))
        try:
            answer = self.runtime(prompt)
        except Exception:
            return None
        return validate_choice(answer, [c[0] for c in candidates])

    def task_prompt(self, candidates: list[tuple[str, int]]) -> list[str]:
        return [*PROMPT_HEADER, "", *[f"- id={cid} open_load={load}" for cid, load in candidates]]

    def propose_for_item(self, item_id: str) -> str:
        candidates = self.candidates()
        choice = self.ask_agent(candidates)
        target = choice["user_id"] if choice else min(candidates, key=lambda c: c[1])[0]
        load = dict(candidates)[target]
        evidence = [{"code": "CANDIDATE_OPEN_LOAD", "value": load}]
        if choice:
            evidence.append({"code": "AGENT_REASON", "value": choice["reason_code"]})
        return self.propose(item_id, target, evidence, agent=choice is not None)

    def propose(self, item_id: str, target_id: str, evidence: list[dict], agent: bool = False) -> str:
        """Records a proposal without effect. The database refuses an item or target of another tenant (C6)."""
        assert_evidence(evidence)
        self.scope()
        pid = str(uuid.uuid4())
        with self.conn:
            self.conn.execute(
                "INSERT INTO proposals (id, tenant_id, item_id, proposer, target_id, evidence) VALUES (?,?,?,?,?,?)",
                (pid, self.tenant_id, item_id, "AGENT" if agent else "RULE", target_id, json.dumps(evidence)))
            signature = ({"task": self.task.task, "model": self.task.model, "prompt_version": self.task.prompt_version}
                         if agent else {})
            self.audit("AGENT" if agent else "SYSTEM", self.task.actor_id if agent else "system",
                       "PROPOSE", pid, {"item_id": item_id, **signature})
        return pid

    # --- decisions -------------------------------------------------------------------------
    def approver_role(self, approver_id: str) -> Optional[str]:
        row = self.conn.execute("SELECT role FROM v_users WHERE id = ?", (approver_id,)).fetchone()
        return row[0] if row else None

    def apply_effect(self, item_id: str, target_id: str) -> None:
        self.conn.execute("UPDATE work_items SET assignee_id = ? WHERE id = ? AND tenant_id = ?",
                          (target_id, item_id, self.tenant_id))

    def decide(self, proposal_id: str, approver_id: str, approve: bool) -> None:
        self.scope()
        row = self.conn.execute("SELECT item_id, target_id, status FROM v_proposals WHERE id = ?", (proposal_id,)).fetchone()
        if row is None:
            raise LookupError("proposal not found")
        if self.approver_role(approver_id) not in APPROVER_ROLES:
            raise AuthorizationError("approver cannot perform this effect directly")
        item_id, target_id, _ = row
        with self.conn:
            self.conn.execute("UPDATE proposals SET status = ?, decided_by = ? WHERE id = ?",
                              ("APPROVED" if approve else "REJECTED", approver_id, proposal_id))
            if approve:
                self.apply_effect(item_id, target_id)
            self.audit("HUMAN", approver_id, "APPROVE" if approve else "REJECT", proposal_id, {"item_id": item_id})

    def audit(self, actor_type: str, actor_id: str, action: str, entity_id: str, data: dict) -> None:
        self.conn.execute("INSERT INTO audit_trail (tenant_id, actor_type, actor_id, action, entity_id, data) "
                          "VALUES (?,?,?,?,?,?)", (self.tenant_id, actor_type, actor_id, action, entity_id, json.dumps(data)))

    def proposals(self, reader_id: str) -> list[tuple]:
        """Lists this tenant's proposals and records the read in the trail under the reader's identity (C5)."""
        self.scope()
        with self.conn:
            rows = self.conn.execute("SELECT id, item_id, target_id, status FROM v_proposals").fetchall()
            self.audit("HUMAN", reader_id, "READ", "proposals", {"proposal_ids": [r[0] for r in rows]})
        return rows
