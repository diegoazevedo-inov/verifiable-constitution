"""Verification coverage of the constitution, per Prohibits clause.

For every clause in constitution/constitution.md:
  1. its checks must PASS against example/ (the guarantee holds);
  2. the same checks must FAIL under every planted violation of the clause (the detector works).
A clause is covered only when both hold. A principle is FULL when all its declared clauses are
covered, PARTIAL when some are, NONE when none are.

Reach is DECLARED in the constitution text and copied into the table; this tool does not measure it.
FULL refers to the declared Prohibits clauses, not to the whole statement of the principle; the parts
declared as not measured are printed in the last column.

Usage: python3 -m tools.coverage   (exit code 1 if any guarantee or detector fails)
"""
import re
import sys
import unittest
from pathlib import Path

from tools.mutants import MUTANTS

ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION = ROOT / "constitution" / "constitution.md"

CHECKS = {
    "C1.a": ["C1.test_c1_proposal_has_no_effect_until_approved"],
    "C1.b": ["C1.test_c1_rule_is_the_floor_when_model_fails"],
    "C2.a": ["C2.test_c2_out_of_list_choice_is_discarded"],
    "C3.a": ["C3.test_c3_empty_evidence_is_rejected", "C3.test_c3_database_rejects_proposal_without_evidence",
             "C3.test_c3_database_rejects_whitespace_only_value", "C3.test_c3_service_rejects_whitespace_only_value"],
    "C3.b": ["C3.test_c3_confidence_is_not_evidence", "C3.test_c3_confidence_only_evidence_with_several_items_is_rejected",
             "C3.test_c3_confidence_is_recognised_as_a_word"],
    "C4.a": ["C4.test_c4_effect_belongs_to_the_approver", "C4.test_c4_rejection_is_recorded_under_the_approver"],
    "C4.b": ["C4.test_c4_unauthorized_approver_is_refused"],
    "C5.a": ["C5.test_c5_trail_is_append_only"],
    "C5.b": ["C5.test_c5_agent_signs_its_proposals"],
    "C5.c": ["C5.test_c5_reading_proposals_is_recorded"],
    "C6.a": ["C6.test_c6_cross_tenant_read_returns_nothing"],
    "C6.b": ["C6.test_c6_proposal_across_tenants_is_refused", "C6.test_c6_pending_proposal_cannot_be_rewritten",
             "C6.test_c6_proposed_item_keeps_its_identity", "C6.test_c6_target_keeps_its_tenant"],
    "C6.c": ["C6.test_c6_approver_from_other_tenant_is_refused", "C6.test_c6_approver_keeps_its_tenant",
             "C6.test_c6_proposal_is_inserted_pending", "C6.test_c6_decision_from_another_tenant_session_is_refused"],
    "C6.d": ["C6.test_c6_effect_across_tenants_is_refused", "C6.test_c6_assignee_keeps_its_tenant"],
    "C7.a": ["C7.test_c7_decided_proposal_is_immutable"],
    "C7.b": ["C7.test_c7_decided_proposal_cannot_be_deleted"],
    "C8.a": ["C8.test_c8_no_eval_no_model_call", "C8.test_c8_eval_for_other_prompt_version_does_not_count",
             "C8.test_c8_eval_for_other_model_or_task_does_not_count"],
    "C9.a": ["C9.test_c9_reason_code_is_restricted_to_the_contract"],
    "C10.a": ["C10.test_c10_every_module_cites_a_decision_record"],
}


def run(test_ids):
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(f"checks.test_constitution.{t}") for t in test_ids)
    result = unittest.TestResult()
    suite.run(result)
    return result.wasSuccessful(), result.testsRun


def classify_clause(tests, mutants, runner=run):
    """Classify one clause. Returns (covered, detail).

    covered is True only when the checks pass on the example and fail under every planted violation.
    A planted violation under which the checks still pass is reported as a blind detector.
    """
    if not tests:
        return False, "no check"
    if not mutants:
        return False, "no planted violation"
    passes, n = runner(tests)
    blind = []
    for name, factory in mutants:
        with factory():
            still_passes, _ = runner(tests)
        caught = not still_passes
        if not caught:
            blind.append(name)
    detail = (f"{n} check(s): {'pass' if passes else 'FAIL'} on example; "
              + (f"fail under all {len(mutants)} planted violation(s)" if not blind
                 else "PASS under " + ", ".join(f"'{b}'" for b in blind) + " (detector blind)"))
    return passes and not blind, detail


def clauses_and_reach():
    """Per principle: title, declared clauses, declared reach and the parts declared as not measured."""
    text = CONSTITUTION.read_text()
    principles = {}
    for block in re.split(r"\n## ", text):
        m = re.match(r"(C\d+) — (.+)", block)
        if not m:
            continue
        clauses = re.findall(r"\*\*Prohibits (C\d+\.[a-z]):\*\*", block)
        reach = re.search(r"Reach: ([^\n]+)", block)
        not_measured = re.search(r"\*\*Not measured:\*\* ([^\n]+)", block)
        principles[m.group(1)] = (m.group(2).strip(), clauses, reach.group(1).strip() if reach else "?",
                                  not_measured.group(1).strip() if not_measured else "—")
    return principles


def main(mutants=None, checks=None, out=None):
    mutants = MUTANTS if mutants is None else mutants
    checks = CHECKS if checks is None else checks
    out = out or sys.stdout
    sys.path.insert(0, str(ROOT))
    rows, ok = [], True
    for pid, (title, clauses, reach, not_measured) in clauses_and_reach().items():
        results = []
        for clause in clauses:
            covered, detail = classify_clause(checks.get(clause, []), mutants.get(clause, []))
            ok = ok and covered
            results.append((clause, covered, detail))
        n_ok = sum(1 for r in results if r[1])
        status = "FULL" if results and n_ok == len(results) else ("PARTIAL" if n_ok else "NONE")
        rows.append((pid, title, status, reach, results, not_measured))
    print("| Principle | Coverage (declared clauses) | Reach (declared, not measured) | Clauses | Not measured |", file=out)
    print("|---|---|---|---|---|", file=out)
    for pid, title, status, reach, results, not_measured in rows:
        detail = "; ".join(f"{c} {'covered' if okc else 'NOT covered'} ({why})" for c, okc, why in results)
        print(f"| {pid} {title} | {status} | {reach} | {detail} | {not_measured} |", file=out)
    totals = {s: sum(1 for r in rows if r[2] == s) for s in ("FULL", "PARTIAL", "NONE")}
    planted = [factory for r in rows for c, _, _ in r[4] for _, factory in mutants.get(c, [])]
    print(f"\nTotals: {totals['FULL']} full, {totals['PARTIAL']} partial, {totals['NONE']} none "
          f"({sum(len(r[4]) for r in rows)} clauses, {len(planted)} clause–violation pairs, "
          f"{len(set(planted))} distinct planted violations; one planted violation can break several clauses).", file=out)
    print("FULL means every declared Prohibits clause of the principle is covered; it does not cover the parts "
          "of the statement listed as not measured. Reach is declared in constitution/constitution.md and is "
          "not measured by this tool.", file=out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
