"""Checks for the generic constitution (constitution/constitution.md), applied to example/workbench.py.

Each test name starts with the principle it verifies. tools/coverage.py runs the checks of every
clause against the example (they must pass) and under each planted violation of that clause
(they must fail).
"""
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from example import workbench as wb

ROOT = Path(__file__).resolve().parents[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = wb.connect(wb.SCHEMA_SQL)
        c = self.conn
        c.executemany("INSERT INTO users VALUES (?,?,?)", [
            ("coord-a", "A", "coordinator"), ("pro-a1", "A", "professional"), ("pro-a2", "A", "professional"),
            ("coord-b", "B", "coordinator"), ("pro-b1", "B", "professional")])
        for tenant, items in (("A", [("item-1", "A", None), ("busy-1", "A", "pro-a1"), ("busy-2", "A", "pro-a1")]),
                              ("B", [("item-b", "B", None)])):
            self.session(tenant)  # work items are inserted under the session of their own tenant (C6.d)
            c.executemany("INSERT INTO work_items VALUES (?,?,?)", items)
        self.tmp = tempfile.TemporaryDirectory()
        self.eval_file = Path(self.tmp.name) / "last-run.json"
        task = wb.AgentTask()
        self.eval_file.write_text(json.dumps({"approved": True, "task": task.task, "model": task.model,
                                              "prompt_version": task.prompt_version}))

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, tenant):
        """Sets the session tenant directly, as any SQL path could, without going through Workbench."""
        self.conn.execute("DELETE FROM session_tenant")
        self.conn.execute("INSERT INTO session_tenant VALUES (?)", (tenant,))

    def refused(self, sql, params=(), msg=None):
        with self.assertRaises(sqlite3.DatabaseError, msg=msg or sql):
            self.conn.execute(sql, params)

    def rows(self, table, order="1"):
        return self.conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()

    def bench(self, runtime=None, eval_file="default", tenant="A"):
        return wb.Workbench(self.conn, tenant, runtime=runtime,
                            eval_file=self.eval_file if eval_file == "default" else eval_file)

    def assignee(self, item):
        return self.conn.execute("SELECT assignee_id FROM work_items WHERE id = ?", (item,)).fetchone()[0]

    def count(self, table):
        return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def trail(self, action):
        return self.conn.execute("SELECT actor_type, actor_id, data FROM audit_trail WHERE action = ? ORDER BY seq",
                                 (action,)).fetchall()


class C1(Base):
    def test_c1_proposal_has_no_effect_until_approved(self):
        b = self.bench()
        pid = b.propose_for_item("item-1")
        self.assertIsNone(self.assignee("item-1"))
        b.decide(pid, "coord-a", approve=True)
        self.assertEqual(self.assignee("item-1"), "pro-a2")

    def test_c1_rule_is_the_floor_when_model_fails(self):
        def broken(_prompt):
            raise RuntimeError("model unavailable")
        b = self.bench(runtime=broken)
        pid = b.propose_for_item("item-1")
        row = self.conn.execute("SELECT proposer, target_id FROM proposals WHERE id = ?", (pid,)).fetchone()
        self.assertEqual(row, ("RULE", "pro-a2"))


class C2(Base):
    def test_c2_out_of_list_choice_is_discarded(self):
        for answer in ({"user_id": "pro-b1"}, {"user_id": "invented"}, {"user_id": ["pro-a1"]}, "pro-a1"):
            b = self.bench(runtime=lambda _p, a=answer: a)
            pid = b.propose_for_item("item-1")
            proposer = self.conn.execute("SELECT proposer FROM proposals WHERE id = ?", (pid,)).fetchone()[0]
            self.assertEqual(proposer, "RULE", answer)


class C3(Base):
    def test_c3_empty_evidence_is_rejected(self):
        with self.assertRaises(wb.EvidenceError):
            self.bench().propose("item-1", "pro-a2", [])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM proposals").fetchone()[0], 0)

    def test_c3_database_rejects_proposal_without_evidence(self):
        self.bench()  # session tenant A, so only the evidence constraint and trigger can refuse the row
        insert = ("INSERT INTO proposals (id, tenant_id, item_id, proposer, target_id, evidence) "
                  "VALUES ('x','A','item-1','RULE','pro-a2',?)")
        for evidence in ("[]", "{}", "[null]", "[{}]", '[{"code": "OPEN_LOAD"}]', '[{"code": "", "value": 1}]',
                         '[{"code": "open load", "value": 1}]', '[{"code": "OPEN_LOAD", "value": "  "}]',
                         '[{"code": "OPEN_LOAD", "value": 0}, {"code": "EMPTY", "value": null}]'):
            self.refused(insert, (evidence,), msg=evidence)
        self.assertEqual(self.count("proposals"), 0)
        self.conn.execute(insert, ('[{"code": "OPEN_LOAD", "value": 0}]',))
        self.assertEqual(self.count("proposals"), 1, "evidence with a code and a value must be accepted")

    def test_c3_confidence_is_not_evidence(self):
        for ev in ([{"code": "CONFIDENCE", "value": 0.9}], [{"code": "MODEL_SCORE", "value": 0.8}]):
            with self.assertRaises(wb.EvidenceError):
                self.bench().propose("item-1", "pro-a2", ev)
        self.bench().propose("item-1", "pro-a2", [{"code": "OPEN_LOAD", "value": 0}, {"code": "CONFIDENCE", "value": 0.9}])


class C4(Base):
    def test_c4_effect_belongs_to_the_approver(self):
        b = self.bench()
        pid = b.propose_for_item("item-1")
        b.decide(pid, "coord-a", approve=True)
        self.assertEqual([r[:2] for r in self.trail("APPROVE")], [("HUMAN", "coord-a")])

    def test_c4_rejection_is_recorded_under_the_approver(self):
        b = self.bench()
        pid = b.propose_for_item("item-1")
        b.decide(pid, "coord-a", approve=False)
        self.assertEqual([r[:2] for r in self.trail("REJECT")], [("HUMAN", "coord-a")])
        self.assertIsNone(self.assignee("item-1"))

    def test_c4_unauthorized_approver_is_refused(self):
        b = self.bench()
        pid = b.propose_for_item("item-1")
        with self.assertRaises(wb.AuthorizationError):
            b.decide(pid, "pro-a1", approve=True)
        self.assertIsNone(self.assignee("item-1"))


class C5(Base):
    def test_c5_trail_is_append_only(self):
        b = self.bench()
        b.decide(b.propose_for_item("item-1"), "coord-a", approve=True)
        before = self.rows("audit_trail", "seq")
        seq, entity = self.conn.execute("SELECT seq, entity_id FROM audit_trail WHERE action = 'APPROVE'").fetchone()
        forged = (seq, "A", "HUMAN", "someone-else", "APPROVE", entity, "{}")
        self.refused("UPDATE audit_trail SET actor_id = 'someone-else'")
        self.refused("DELETE FROM audit_trail")
        self.refused("INSERT OR REPLACE INTO audit_trail VALUES (?,?,?,?,?,?,?)", forged)
        self.refused("REPLACE INTO audit_trail VALUES (?,?,?,?,?,?,?)", forged)
        self.refused("INSERT INTO audit_trail VALUES (?,?,?,?,?,?,?) "
                     "ON CONFLICT(seq) DO UPDATE SET actor_id = excluded.actor_id", forged)
        self.refused("UPDATE OR REPLACE audit_trail SET seq = 1 WHERE seq = ?", (seq,))
        self.session("B")
        self.refused("UPDATE audit_trail SET actor_id = 'someone-else'")
        self.refused("DELETE FROM audit_trail")
        self.assertEqual(self.rows("audit_trail", "seq"), before)

    def test_c5_agent_signs_its_proposals(self):
        b = self.bench(runtime=lambda _p: {"user_id": "pro-a1", "reason_code": "SPECIALTY"})
        b.propose_for_item("item-1")
        [(actor_type, actor_id, data)] = self.trail("PROPOSE")
        task = wb.AgentTask()
        self.assertEqual((actor_type, actor_id), ("AGENT", task.actor_id))
        signature = json.loads(data)
        self.assertEqual(signature.get("model"), task.model)
        self.assertEqual(signature.get("prompt_version"), task.prompt_version)

    def test_c5_reading_proposals_is_recorded(self):
        b = self.bench()
        pid = b.propose_for_item("item-1")
        before = self.count("audit_trail")
        rows = b.proposals(reader_id="coord-a")
        self.assertEqual([r[0] for r in rows], [pid])
        self.assertEqual(self.count("audit_trail"), before + 1)
        [(actor_type, actor_id, data)] = self.trail("READ")
        self.assertEqual((actor_type, actor_id), ("HUMAN", "coord-a"))
        self.assertEqual(json.loads(data)["proposal_ids"], [pid])


class C6(Base):
    EVIDENCE = [{"code": "OPEN_LOAD", "value": 0}]

    def test_c6_cross_tenant_read_returns_nothing(self):
        pid_b = wb.Workbench(self.conn, "B").propose("item-b", "pro-b1", self.EVIDENCE)
        a = self.bench(tenant="A")
        self.assertEqual(a.proposals(reader_id="coord-a"), [])
        self.assertEqual([c[0] for c in a.candidates()], ["pro-a1", "pro-a2"])
        with self.assertRaises(LookupError):
            a.decide(pid_b, "coord-a", approve=True)
        self.assertIsNone(self.assignee("item-b"))

    def test_c6_proposal_across_tenants_is_refused(self):
        a = self.bench(tenant="A")
        for item, target in (("item-1", "pro-b1"), ("item-b", "pro-a1"), ("item-b", "pro-b1")):
            with self.assertRaises(sqlite3.IntegrityError, msg=(item, target)):
                a.propose(item, target, self.EVIDENCE)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO proposals (id, tenant_id, item_id, proposer, target_id, evidence) "
                              "VALUES ('x', 'B', 'item-b', 'RULE', 'pro-b1', '[{\"code\": \"OPEN_LOAD\", \"value\": 0}]')")
        self.assertEqual(self.count("proposals"), 0)

    def test_c6_pending_proposal_cannot_be_rewritten(self):
        pid_b = wb.Workbench(self.conn, "B").propose("item-b", "pro-b1", self.EVIDENCE)
        a = self.bench(tenant="A")
        pid = a.propose_for_item("item-1")
        before = self.rows("proposals", "id")
        for column, value in (("target_id", "pro-b1"), ("item_id", "item-b"), ("tenant_id", "B"), ("target_id", "pro-a1"),
                              ("proposer", "AGENT"), ("evidence", '[{"code": "OTHER", "value": 1}]'), ("id", "renamed")):
            self.refused(f"UPDATE proposals SET {column} = ? WHERE id = ?", (value, pid), msg=column)
        rewritten = (pid, "A", "item-1", "AGENT", "pro-a1", '[{"code": "OTHER", "value": 1}]')
        columns = "(id, tenant_id, item_id, proposer, target_id, evidence)"
        for verb in ("INSERT OR REPLACE", "REPLACE"):
            self.refused(f"{verb} INTO proposals {columns} VALUES (?,?,?,?,?,?)", rewritten, msg=verb)
            self.refused(f"{verb} INTO proposals {columns} VALUES (?,?,?,?,?,?)", (pid_b, *rewritten[1:]),
                         msg=f"{verb} of another tenant's proposal")
        self.refused(f"INSERT INTO proposals {columns} VALUES (?,?,?,?,?,?) "
                     "ON CONFLICT(id) DO UPDATE SET target_id = excluded.target_id, evidence = excluded.evidence", rewritten)
        self.refused("DELETE FROM proposals WHERE id = ?", (pid,))
        self.assertEqual(self.rows("proposals", "id"), before)

    def test_c6_proposed_item_keeps_its_identity(self):
        self.bench(tenant="A").propose_for_item("item-1")
        self.refused("UPDATE work_items SET id = 'item-z' WHERE id = 'item-1'")
        self.refused("DELETE FROM work_items WHERE id = 'item-1'")
        self.session("B")  # another tenant cannot take the id over
        self.refused("REPLACE INTO work_items VALUES ('item-1', 'B', NULL)")
        self.assertEqual(self.conn.execute("SELECT tenant_id FROM work_items WHERE id = 'item-1'").fetchone(), ("A",))

    def assert_user_keeps_tenant(self, user_id, role):
        before = self.rows("users", "id")
        self.refused("UPDATE users SET tenant_id = 'B' WHERE id = ?", (user_id,))
        self.refused("UPDATE users SET id = 'renamed' WHERE id = ?", (user_id,))
        self.refused("DELETE FROM users WHERE id = ?", (user_id,))
        self.refused("REPLACE INTO users VALUES (?, 'B', ?)", (user_id, role))
        self.assertEqual(self.rows("users", "id"), before)

    def test_c6_target_keeps_its_tenant(self):
        self.bench(tenant="A").propose("item-1", "pro-a2", self.EVIDENCE)
        self.assert_user_keeps_tenant("pro-a2", "professional")

    def test_c6_approver_keeps_its_tenant(self):
        a = self.bench(tenant="A")
        a.decide(a.propose("item-1", "pro-a2", self.EVIDENCE), "coord-a", approve=False)
        self.assert_user_keeps_tenant("coord-a", "coordinator")

    def test_c6_assignee_keeps_its_tenant(self):
        self.bench(tenant="A")
        self.assertEqual(self.assignee("busy-1"), "pro-a1")
        self.assert_user_keeps_tenant("pro-a1", "professional")

    def test_c6_approver_from_other_tenant_is_refused(self):
        a = self.bench(tenant="A")
        pid = a.propose_for_item("item-1")
        with self.assertRaises(wb.AuthorizationError):
            a.decide(pid, "coord-b", approve=True)
        self.refused("UPDATE proposals SET status = 'APPROVED', decided_by = 'coord-b' WHERE id = ?", (pid,))
        evidence = json.dumps(self.EVIDENCE)
        self.refused("INSERT INTO proposals VALUES (?, 'A', 'item-1', 'RULE', 'pro-a2', ?, ?, ?) "
                     "ON CONFLICT(id) DO UPDATE SET status = excluded.status, decided_by = excluded.decided_by",
                     (pid, evidence, "APPROVED", "coord-b"))
        # a proposal is born pending: it cannot be inserted already decided, by another tenant's user or by anyone
        for status, decided_by in (("APPROVED", "coord-b"), ("PENDING", "coord-b"), ("REJECTED", "coord-b"),
                                   ("APPROVED", "coord-a")):
            for verb in ("INSERT", "INSERT OR REPLACE"):
                self.refused(f"{verb} INTO proposals VALUES (?, 'A', 'item-1', 'RULE', 'pro-a2', ?, ?, ?)",
                             ("p2" if verb == "INSERT" else pid, evidence, status, decided_by),
                             msg=(verb, status, decided_by))
        self.assertEqual(self.conn.execute("SELECT id, status, decided_by FROM proposals").fetchall(),
                         [(pid, "PENDING", None)])
        self.assertIsNone(self.assignee("item-1"))

    def test_c6_effect_across_tenants_is_refused(self):
        self.bench(tenant="A")
        before = self.rows("work_items", "id")
        for item, assignee in (("item-b", "pro-b1"), ("item-b", "pro-a1"), ("item-1", "pro-b1")):
            self.refused("UPDATE work_items SET assignee_id = ? WHERE id = ?", (assignee, item), msg=(item, assignee))
        self.refused("UPDATE work_items SET tenant_id = 'B' WHERE id = 'item-1'")
        # inserted already assigned to another tenant's user, or into another tenant from this session
        for row in (("item-x", "A", "pro-b1"), ("item-y", "B", None), ("item-z", "B", "pro-b1")):
            self.refused("INSERT INTO work_items VALUES (?,?,?)", row, msg=row)
        self.refused("DELETE FROM work_items WHERE id = 'item-b'")
        self.refused("INSERT OR REPLACE INTO work_items VALUES ('item-b', 'A', NULL)")
        self.refused("REPLACE INTO work_items VALUES ('item-b', 'A', 'pro-a1')")
        self.refused("INSERT INTO work_items VALUES ('item-b', 'A', NULL) "
                     "ON CONFLICT(id) DO UPDATE SET assignee_id = 'pro-a1'")
        self.refused("UPDATE OR REPLACE work_items SET id = 'item-b' WHERE id = 'item-1'")
        self.assertEqual(self.rows("work_items", "id"), before)


class C7(Base):
    def test_c7_decided_proposal_is_immutable(self):
        b = self.bench()
        pid = b.propose_for_item("item-1")
        b.decide(pid, "coord-a", approve=False)
        pending = b.propose("item-1", "pro-a1", [{"code": "OPEN_LOAD", "value": 0}])
        before = self.rows("proposals", "id")
        self.refused("UPDATE proposals SET status = 'APPROVED' WHERE id = ?", (pid,))
        rewritten = (pid, "A", "item-1", "RULE", "pro-a1", '[{"code": "OPEN_LOAD", "value": 0}]')
        columns = "(id, tenant_id, item_id, proposer, target_id, evidence)"
        for verb in ("INSERT OR REPLACE", "REPLACE"):
            self.refused(f"{verb} INTO proposals {columns} VALUES (?,?,?,?,?,?)", rewritten, msg=verb)
        self.refused(f"INSERT INTO proposals {columns} VALUES (?,?,?,?,?,?) "
                     "ON CONFLICT(id) DO UPDATE SET status = 'PENDING'", rewritten)
        self.refused("UPDATE OR REPLACE proposals SET id = ? WHERE id = ?", (pid, pending))
        self.assertEqual(self.rows("proposals", "id"), before)

    def test_c7_decided_proposal_cannot_be_deleted(self):
        b = self.bench()
        decided = b.propose_for_item("item-1")
        b.decide(decided, "coord-a", approve=True)
        self.refused("DELETE FROM proposals WHERE id = ?", (decided,))
        self.refused("REPLACE INTO proposals (id, tenant_id, item_id, proposer, target_id, evidence) "
                     "VALUES (?, 'A', 'item-1', 'RULE', 'pro-a1', '[{\"code\": \"OPEN_LOAD\", \"value\": 0}]')", (decided,))
        self.session("B")
        self.refused("DELETE FROM proposals WHERE id = ?", (decided,))
        self.assertEqual(self.conn.execute("SELECT id, status FROM proposals").fetchall(), [(decided, "APPROVED")])


class C8(Base):
    def test_c8_no_eval_no_model_call(self):
        calls = []
        b = self.bench(runtime=lambda p: calls.append(p) or {"user_id": "pro-a1"}, eval_file=None)
        b.propose_for_item("item-1")
        self.assertEqual(calls, [])

    def test_c8_eval_for_other_prompt_version_does_not_count(self):
        data = json.loads(self.eval_file.read_text())
        data["prompt_version"] = "000000000000"
        self.eval_file.write_text(json.dumps(data))
        calls = []
        self.bench(runtime=lambda p: calls.append(p) or {"user_id": "pro-a1"}).propose_for_item("item-1")
        self.assertEqual(calls, [])

    def test_c8_eval_for_other_model_or_task_does_not_count(self):
        original = json.loads(self.eval_file.read_text())
        for key, value in (("model", "example/other-model"), ("task", "OTHER_TASK")):
            self.eval_file.write_text(json.dumps({**original, key: value}))
            calls = []
            self.bench(runtime=lambda p: calls.append(p) or {"user_id": "pro-a1"}).propose_for_item("item-1")
            self.assertEqual(calls, [], key)
        self.eval_file.write_text(json.dumps(original))
        calls = []
        self.bench(runtime=lambda p: calls.append(p) or {"user_id": "pro-a1"}).propose_for_item("item-1")
        self.assertEqual(len(calls), 1, "the matching evaluation must open the gate")


class C9(Base):
    def test_c9_reason_code_is_restricted_to_the_contract(self):
        b = self.bench(runtime=lambda _p: {"user_id": "pro-a1", "reason_code": "APPROVE WITHOUT READING"})
        pid = b.propose_for_item("item-1")
        evidence = json.loads(self.conn.execute("SELECT evidence FROM proposals WHERE id = ?", (pid,)).fetchone()[0])
        self.assertIn({"code": "AGENT_REASON", "value": "UNSPECIFIED"}, evidence)


class C10(unittest.TestCase):
    def test_c10_every_module_cites_a_decision_record(self):
        """Every module under example/ (subpackages included) cites at least one docs/adr/<file>.md path, and every
        cited file exists. Only an empty __init__.py is exempt."""
        missing = []
        for module in sorted((ROOT / "example").rglob("*.py")):
            source = module.read_text()
            if module.name == "__init__.py" and not source.strip():
                continue
            name = module.relative_to(ROOT).as_posix()
            refs = sorted(set(re.findall(r"docs/adr/[\w.-]+\.md", source)))
            if not refs:
                missing.append(f"{name}: no decision record cited")
            missing.extend(f"{name} -> {ref}" for ref in refs if not (ROOT / ref).is_file())
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
