"""Self-test of the measuring tool (tools/coverage.py).

A planted violation that breaks nothing (a no-op) must be reported as a blind detector: the clause is
NOT covered and the tool exits with a code other than 0. If the classification logic stopped comparing
the checks under the violation, these tests would fail.
"""
import contextlib
import io
import unittest

from tools import coverage
from tools.mutants import MUTANTS

NOOP = ("no-op planted violation", contextlib.nullcontext)


class CoverageToolSelfTest(unittest.TestCase):
    def test_noop_mutant_is_reported_as_blind(self):
        covered, detail = coverage.classify_clause(coverage.CHECKS["C7.a"], [NOOP])
        self.assertFalse(covered, detail)
        self.assertIn("detector blind", detail)

    def test_noop_mutant_among_real_ones_is_still_blind(self):
        covered, detail = coverage.classify_clause(coverage.CHECKS["C7.a"], [*MUTANTS["C7.a"], NOOP])
        self.assertFalse(covered, detail)
        self.assertIn(NOOP[0], detail)

    def test_real_mutant_is_reported_as_covered(self):
        covered, detail = coverage.classify_clause(coverage.CHECKS["C7.a"], MUTANTS["C7.a"])
        self.assertTrue(covered, detail)

    def test_check_failing_on_the_example_is_not_covered(self):
        covered, detail = coverage.classify_clause(["C7.test_does_not_exist"], MUTANTS["C7.a"])
        self.assertFalse(covered, detail)
        self.assertIn("FAIL on example", detail)

    def test_clause_without_check_or_mutant_is_not_covered(self):
        self.assertEqual(coverage.classify_clause([], MUTANTS["C7.a"]), (False, "no check"))
        self.assertEqual(coverage.classify_clause(coverage.CHECKS["C7.a"], []), (False, "no planted violation"))

    def test_tool_exits_non_zero_when_a_detector_is_blind(self):
        out = io.StringIO()
        code = coverage.main(mutants={**MUTANTS, "C7.a": [NOOP]}, out=out)
        self.assertNotEqual(code, 0)
        line = next(l for l in out.getvalue().splitlines() if l.startswith("| C7 "))
        self.assertIn("C7.a NOT covered", line)
        self.assertIn("detector blind", line)
        self.assertIn("| PARTIAL |", line)

    def test_every_clause_in_the_constitution_has_checks_and_a_mutant(self):
        clauses = [c for _, cl, _, _ in coverage.clauses_and_reach().values() for c in cl]
        self.assertEqual(sorted(clauses), sorted(coverage.CHECKS))
        self.assertEqual(sorted(clauses), sorted(MUTANTS))
        self.assertTrue(all(MUTANTS[c] for c in clauses))


if __name__ == "__main__":
    unittest.main()
