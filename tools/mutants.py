"""Planted violations: one or more per Prohibits clause of constitution/constitution.md.

Each mutant is a context manager that breaks one guarantee of example/workbench.py.
A clause counts as covered only if its checks pass on the example AND fail under every one of its mutants.
MUTANTS maps each clause to a list of (description, factory) pairs.
"""
import contextlib
import json
from pathlib import Path

from example import workbench as wb

ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def patched(obj, name, value):
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, original)


def schema_with(*replacements):
    """Schema in which each (fragment, replacement) pair is applied; every fragment must exist."""
    sql = wb.SCHEMA_SQL
    for fragment, replacement in replacements:
        assert fragment in sql, fragment
        sql = sql.replace(fragment, replacement)
    return patched(wb, "SCHEMA_SQL", sql)


def schema_without(fragment, replacement=""):
    return schema_with((fragment, replacement))


def trigger(name):
    """Full text of a CREATE TRIGGER statement in the example schema."""
    start = wb.SCHEMA_SQL.index(f"CREATE TRIGGER {name} ")
    return wb.SCHEMA_SQL[start:wb.SCHEMA_SQL.index("END;", start) + len("END;")]


def stacked(*contexts):
    stack = contextlib.ExitStack()
    for context in contexts:
        stack.enter_context(context)
    return stack


def audit_filter(change):
    """Mutant of Workbench.audit: change(actor_type, actor_id, action, data) returns new values or None to drop."""
    original = wb.Workbench.audit

    def audit(self, actor_type, actor_id, action, entity_id, data):
        changed = change(actor_type, actor_id, action, data)
        if changed is not None:
            original(self, *changed[:3], entity_id, changed[3])
    return patched(wb.Workbench, "audit", audit)


@contextlib.contextmanager
def rogue_module(source, relative="zz_planted_module.py"):
    """Writes a planted module under example/ (creating its folder if needed) and removes it afterwards."""
    rogue = ROOT / "example" / relative
    created = [d for d in reversed(rogue.relative_to(ROOT / "example").parents) if not (ROOT / "example" / d).exists()]
    rogue.parent.mkdir(parents=True, exist_ok=True)
    rogue.write_text(source)
    try:
        yield
    finally:
        rogue.unlink(missing_ok=True)
        for folder in reversed(created):
            (ROOT / "example" / folder).rmdir()


def recursive_triggers_off():  # connections no longer fire DELETE triggers for rows removed by REPLACE
    original = wb.connect

    def connect(schema_sql=None):
        conn = original(schema_sql)
        conn.execute("PRAGMA recursive_triggers = OFF")
        return conn
    return patched(wb, "connect", connect)


# --- C1 ----------------------------------------------------------------------------------------
def c1a():  # effect applied at proposal time
    original = wb.Workbench.propose

    def propose(self, item_id, target_id, evidence, agent=False):
        pid = original(self, item_id, target_id, evidence, agent)
        self.conn.execute("UPDATE work_items SET assignee_id = ? WHERE id = ?", (target_id, item_id))
        return pid
    return patched(wb.Workbench, "propose", propose)


def c1b():  # no deterministic floor: model failure propagates
    def ask_agent(self, candidates):
        return self.runtime("\n".join(self.task_prompt(candidates)))
    return patched(wb.Workbench, "ask_agent", ask_agent)


# --- C2 ----------------------------------------------------------------------------------------
def c2a():  # model may name anyone
    return patched(wb, "validate_choice", lambda data, ids: (
        {"user_id": data.get("user_id"), "reason_code": "UNSPECIFIED"} if isinstance(data, dict) and isinstance(data.get("user_id"), str) else None))


# --- C3 ----------------------------------------------------------------------------------------
def c3a():  # evidence not enforced in the service nor in the database
    return stacked(patched(wb, "assert_evidence", lambda evidence: None),
                   schema_without("CHECK (json_valid(evidence) AND json_array_length(evidence) > 0)"))


def c3a_items_unchecked():  # the database accepts evidence items without a code or a value
    return schema_without(trigger("proposals_evidence_items"))


def c3a_whitespace_value_accepted():  # the database takes a value of tabs or line breaks as non-empty (spaces only)
    return schema_without("trim(json_extract(e.value, '$.value'), ' ' || char(9, 10, 11, 12, 13)) = ''",
                          "trim(json_extract(e.value, '$.value')) = ''")


def c3b():  # confidence accepted as evidence
    return patched(wb, "CONFIDENCE_CODE", __import__("re").compile(r"$^"))


def c3b_single_item_only():  # confidence refused only when it is the single evidence item
    original = wb.assert_evidence

    def assert_evidence(evidence):
        if isinstance(evidence, list) and len(evidence) > 1:
            evidence = [*evidence, {"code": "PLANTED_FACT", "value": 1}]  # every item is still checked; the rule never fires
        original(evidence)
    return patched(wb, "assert_evidence", assert_evidence)


CONFIDENCE_WORDS = "(CONFIDENCE|SCORE|PROBABILITY|CERTAINTY|LIKELIHOOD)"


def c3b_substring_rule():  # confidence words matched anywhere in the code, not as words (SCOREBOARD_ID refused)
    assert wb.CONFIDENCE_CODE.pattern == rf"(^|_){CONFIDENCE_WORDS}(_|$)"
    return patched(wb, "CONFIDENCE_CODE", __import__("re").compile(CONFIDENCE_WORDS))


def c3b_whole_code_rule():  # only a code that is exactly a confidence word counts (MODEL_SCORE accepted)
    return patched(wb, "CONFIDENCE_CODE", __import__("re").compile(rf"^{CONFIDENCE_WORDS}$"))


# --- C4 ----------------------------------------------------------------------------------------
def c4a_effect_as_system():  # effect recorded as SYSTEM, not as the approver
    return audit_filter(lambda t, a, action, data: ("SYSTEM", "system", action, data) if t == "HUMAN" else (t, a, action, data))


def c4a_rejection_not_recorded():  # a rejection leaves no trail entry
    return audit_filter(lambda t, a, action, data: None if action == "REJECT" else (t, a, action, data))


def c4b():  # anyone may approve
    return patched(wb, "APPROVER_ROLES", ("coordinator", "professional"))


# --- C5 ----------------------------------------------------------------------------------------
def c5a():  # trail can be rewritten
    return schema_with((trigger("audit_no_update"), ""), (trigger("audit_no_delete"), ""))


def c5b_signed_as_system():  # agent proposals signed as SYSTEM
    return audit_filter(lambda t, a, action, data: ("SYSTEM", "system", action, {k: v for k, v in data.items() if k == "item_id"})
                        if t == "AGENT" else (t, a, action, data))


def c5b_signature_without_model():  # agent signature drops the model
    return audit_filter(lambda t, a, action, data: (t, a, action, {k: v for k, v in data.items() if k != "model"})
                        if t == "AGENT" else (t, a, action, data))


def c5c():  # reads of proposals are not recorded
    def proposals(self, reader_id):
        self.scope()
        return self.conn.execute("SELECT id, item_id, target_id, status FROM v_proposals").fetchall()
    return patched(wb.Workbench, "proposals", proposals)


# --- C6 ----------------------------------------------------------------------------------------
VIEW_FILTER = " WHERE tenant_id = (SELECT tenant_id FROM session_tenant);"


def c6a_views_unfiltered():  # tenant-scoped views return every tenant
    assert wb.SCHEMA_SQL.count(VIEW_FILTER) == 3
    return patched(wb, "SCHEMA_SQL", wb.SCHEMA_SQL.replace(VIEW_FILTER, ";"))


def c6a_candidates_unscoped():  # candidates read from the base table without a tenant filter
    def candidates(self):
        self.scope()
        rows = self.conn.execute(
            "SELECT u.id, (SELECT count(*) FROM v_work_items w WHERE w.assignee_id = u.id) "
            "FROM users u WHERE u.role = 'professional' ORDER BY u.id")
        return [(r[0], r[1]) for r in rows]
    return patched(wb.Workbench, "candidates", candidates)


def c6b_insert_unchecked():  # a proposal may reference another tenant's item or target
    return schema_without(trigger("proposals_same_tenant"))


def c6b_rewrite_allowed():  # a pending proposal's item, target or tenant may be rewritten
    return schema_without(trigger("proposals_content_fixed"))


CONTENT_COLUMNS = ("id", "tenant_id", "item_id", "proposer", "target_id", "evidence")


def c6b_rewrite_allowed_for(column):
    """The content trigger without one of its columns (proposer and evidence together reproduce audit defect T5)."""
    kept = ", ".join(c for c in CONTENT_COLUMNS if c != column)
    return lambda: schema_without(f"UPDATE OF {', '.join(CONTENT_COLUMNS)} ON proposals", f"UPDATE OF {kept} ON proposals")


def c6b_pending_deletable():  # only decided proposals are retained, so REPLACE can rewrite a pending one
    return schema_without(trigger("proposals_retained"),
                          "CREATE TRIGGER proposals_retained BEFORE DELETE ON proposals WHEN OLD.status <> 'PENDING' "
                          "BEGIN SELECT RAISE(ABORT, 'proposal must be retained'); END;")


def c6b_item_id_mutable():  # a proposed work item may be renamed, so another tenant can take its id
    return schema_without(trigger("work_items_id_fixed"))


def c6b_proposed_item_deletable():  # a proposed work item may be deleted, so another tenant can take its id
    return schema_without(trigger("work_items_retained_when_proposed"))


def c6_user_identity_mutable():  # a referenced user may move to another tenant or be renamed
    return schema_without(trigger("users_identity_fixed"))


def c6_referenced_user_deletable():  # a referenced user may be deleted and recreated in another tenant
    return schema_without(trigger("users_retained_when_referenced"))


def c6c_approver_unscoped():  # approver looked up in the base table without a tenant filter
    def approver_role(self, approver_id):
        row = self.conn.execute("SELECT role FROM users WHERE id = ?", (approver_id,)).fetchone()
        return row[0] if row else None
    return patched(wb.Workbench, "approver_role", approver_role)


def c6c_decision_unchecked():  # the database accepts a decision by another tenant's user
    return schema_without(trigger("proposals_decided_in_tenant"))


def c6c_inserted_decided():  # a proposal may be inserted already decided, skipping the checked update
    return schema_without(trigger("proposals_inserted_pending"))


def c6c_inserted_with_status():  # the pending rule checks only the approver: a decided status without one is accepted
    text = trigger("proposals_inserted_pending")
    assert "NEW.status IS NOT 'PENDING' OR " in text
    return schema_without(text, text.replace("NEW.status IS NOT 'PENDING' OR ", ""))


def c6c_decided_from_other_session():  # the decision is checked against the approver's tenant but not the session's
    text = trigger("proposals_decided_in_tenant")
    fragment = "OLD.tenant_id IS NOT (SELECT tenant_id FROM session_tenant)\n    OR "
    assert fragment in text
    return schema_without(text, text.replace(fragment, ""))


def c6d():  # effect without tenant scope, in the service and in the database
    def apply_effect(self, item_id, target_id):
        self.conn.execute("UPDATE work_items SET assignee_id = ? WHERE id = ?", (target_id, item_id))
    return stacked(patched(wb.Workbench, "apply_effect", apply_effect),
                   schema_without(trigger("work_items_same_tenant")))


def c6d_insert_unchecked():  # a work item may be inserted into another tenant or assigned to another tenant's user
    return schema_without(trigger("work_items_inserted_in_tenant"))


def c6d_delete_unchecked():  # another tenant's work item may be deleted
    return schema_without(trigger("work_items_deleted_in_tenant"))


# --- C7 ----------------------------------------------------------------------------------------
def c7a():  # decided proposal can change
    return schema_without(trigger("proposals_immutable_when_decided"))


def c7b():  # decided proposal can be deleted
    return schema_without(trigger("proposals_retained"))


# --- C8 ----------------------------------------------------------------------------------------
def c8a_gate_ignores_eval():  # gate ignores the evaluation
    return patched(wb, "eval_approved", lambda eval_file, task: True)


def gate_ignoring(field):
    """The evaluation gate of example/workbench.py without the comparison of one field."""
    fields = [f for f in ("task", "model", "prompt_version") if f != field]

    def eval_approved(eval_file, task):
        if eval_file is None or not Path(eval_file).is_file():
            return False
        result = json.loads(Path(eval_file).read_text())
        return result.get("approved") is True and all(result.get(f) == getattr(task, f) for f in fields)
    return patched(wb, "eval_approved", eval_approved)


def c8a_gate_ignores_model():  # gate does not compare the model
    return gate_ignoring("model")


def c8a_gate_ignores_task():  # gate does not compare the task
    return gate_ignoring("task")


# --- C9 ----------------------------------------------------------------------------------------
def c9a():  # free text from the model passes through as evidence
    original = wb.validate_choice

    def validate(data, ids):
        r = original(data, ids)
        if r and isinstance(data, dict) and isinstance(data.get("reason_code"), str):
            r["reason_code"] = data["reason_code"]
        return r
    return patched(wb, "validate_choice", validate)


# --- C10 ---------------------------------------------------------------------------------------
def c10a_no_reference():  # a production module without a decision record
    return rogue_module('"""Planted violation: no decision record."""\n')


def c10a_vague_reference():  # the module mentions the ADR folder but cites no record
    return rogue_module('"""Planted violation.\n\nDecision records: none (see docs/adr/ later)\n"""\n')


def c10a_missing_record():  # the module cites a decision record that does not exist
    return rogue_module('"""Planted violation.\n\nDecision records: docs/adr/9999-not-written.md\n"""\n')


def c10a_module_in_subpackage():  # a module in a subfolder of example/ without a decision record
    return rogue_module('"""Planted violation: no decision record."""\n', "zz_planted_pkg/module.py")


def c10a_code_in_init():  # a package __init__.py with code and without a decision record
    return rogue_module('"""Planted violation: code in __init__.py."""\nVALUE = 1\n', "zz_planted_pkg/__init__.py")


MUTANTS = {
    "C1.a": [("effect applied at proposal time", c1a)],
    "C1.b": [("model failure propagates, no deterministic floor", c1b)],
    "C2.a": [("model may name any id", c2a)],
    "C3.a": [("evidence enforced neither in the service nor in the database", c3a),
             ("database accepts evidence items without code or value", c3a_items_unchecked),
             ("database accepts a value made only of tabs or line breaks", c3a_whitespace_value_accepted)],
    "C3.b": [("confidence codes accepted as evidence", c3b),
             ("confidence refused only as the single evidence item", c3b_single_item_only),
             ("confidence words matched inside other words", c3b_substring_rule),
             ("confidence recognised only as the whole code", c3b_whole_code_rule)],
    "C4.a": [("approval recorded as SYSTEM", c4a_effect_as_system),
             ("rejection not recorded", c4a_rejection_not_recorded)],
    "C4.b": [("any role may approve", c4b)],
    "C5.a": [("trail triggers removed", c5a),
             ("recursive triggers off: REPLACE rewrites trail entries", recursive_triggers_off)],
    "C5.b": [("agent proposal signed as SYSTEM", c5b_signed_as_system),
             ("agent signature without model", c5b_signature_without_model)],
    "C5.c": [("read of proposals not recorded", c5c)],
    "C6.a": [("tenant-scoped views unfiltered", c6a_views_unfiltered),
             ("candidates read without tenant filter", c6a_candidates_unscoped)],
    "C6.b": [("proposal insert not checked for tenant", c6b_insert_unchecked),
             ("pending proposal content may be rewritten", c6b_rewrite_allowed),
             *[(f"pending proposal {column} may be rewritten", c6b_rewrite_allowed_for(column)) for column in CONTENT_COLUMNS],
             ("pending proposal may be deleted, so REPLACE rewrites it", c6b_pending_deletable),
             ("recursive triggers off: REPLACE rewrites a pending proposal", recursive_triggers_off),
             ("proposed work item may be renamed", c6b_item_id_mutable),
             ("proposed work item may be deleted", c6b_proposed_item_deletable),
             ("target user may change tenant or id", c6_user_identity_mutable),
             ("target user may be deleted", c6_referenced_user_deletable)],
    "C6.c": [("approver looked up without tenant filter", c6c_approver_unscoped),
             ("database accepts decision by another tenant's user", c6c_decision_unchecked),
             ("proposal may be inserted already decided", c6c_inserted_decided),
             ("proposal may be inserted decided without an approver", c6c_inserted_with_status),
             ("decision accepted from another tenant's session", c6c_decided_from_other_session),
             ("approver may change tenant or id", c6_user_identity_mutable),
             ("approver may be deleted", c6_referenced_user_deletable)],
    "C6.d": [("effect without tenant scope in service and database", c6d),
             ("work item insert not checked for tenant", c6d_insert_unchecked),
             ("another tenant's work item may be deleted", c6d_delete_unchecked),
             ("recursive triggers off: REPLACE takes another tenant's work item", recursive_triggers_off),
             ("assignee may change tenant or id", c6_user_identity_mutable),
             ("assignee may be deleted", c6_referenced_user_deletable)],
    "C7.a": [("decided proposal may change", c7a),
             ("recursive triggers off: REPLACE rewrites a decided proposal", recursive_triggers_off)],
    "C7.b": [("decided proposal may be deleted", c7b),
             ("recursive triggers off: REPLACE deletes a decided proposal", recursive_triggers_off)],
    "C8.a": [("gate ignores the evaluation", c8a_gate_ignores_eval),
             ("gate ignores the model", c8a_gate_ignores_model),
             ("gate ignores the task", c8a_gate_ignores_task)],
    "C9.a": [("model free text passes as evidence", c9a)],
    "C10.a": [("module without decision record", c10a_no_reference),
              ("module mentions docs/adr/ without citing a record", c10a_vague_reference),
              ("module cites a missing decision record", c10a_missing_record),
              ("module in a subfolder without decision record", c10a_module_in_subpackage),
              ("__init__.py with code and without decision record", c10a_code_in_init)],
}
