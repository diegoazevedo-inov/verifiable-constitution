"""Checks for the anonymised case-study data (case-study/): the agreement statistics reported in the
accompanying manuscript are reproduced from principles.csv, the stored output is
current, and the per-principle totals and clause counts match the three measurements.

Includes a planted violation: changing one classification must change the statistics, so the
expected values below cannot be met by a script that ignores its input.
"""
import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "case-study"


def load_concordance():
    spec = importlib.util.spec_from_file_location("concordance", CASE / "concordance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


conc = load_concordance()


class CaseStudyData(unittest.TestCase):
    def setUp(self):
        self.principles = conc.load_principles()

    def test_principles_csv_has_sixteen_rows_in_order(self):
        self.assertEqual(len(self.principles), 16)
        self.assertEqual([p["id"] for p in self.principles],
                         ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
                          "XI", "XII", "XIII", "XIV", "XV", "XVI"])

    def test_totals_full_partial_none(self):
        self.assertEqual(conc.totals(self.principles, "m1"), (2, 6, 8))
        self.assertEqual(conc.totals(self.principles, "m2"), (5, 3, 8))
        self.assertEqual(conc.totals(self.principles, "m3"), (3, 3, 10))

    def test_behaviour_changed_only_in_v_and_xiii(self):
        changed = [p["id"] for p in self.principles if p["behaviour_changed_m2_m3"] == "yes"]
        self.assertEqual(changed, ["V", "XIII"])

    def test_behaviour_changed_m1_m2_in_iii_v_vii_x(self):
        self.assertEqual(conc.changed(self.principles, "behaviour_changed_m1_m2"), ["III", "V", "VII", "X"])

    def test_m2_x_m3_agreement(self):
        r = conc.compare(self.principles, "m2", "m3", conc.changed(self.principles, "behaviour_changed_m2_m3"))
        self.assertEqual((r["agree"], r["n"]), (10, 14))
        self.assertEqual(round(r["kappa"], 3), 0.486)
        self.assertEqual(round(r["weighted_kappa"], 3), 0.611)
        self.assertEqual([d[0] for d in r["divergent"]], ["III", "IV", "X", "XI"])

    def test_m1_x_m2_agreement(self):
        r = conc.compare(self.principles, "m1", "m2", conc.changed(self.principles, "behaviour_changed_m1_m2"))
        self.assertEqual((r["agree"], r["n"]), (10, 12))
        self.assertEqual(round(r["kappa"], 3), 0.667)
        self.assertEqual(round(r["weighted_kappa"], 3), 0.769)
        self.assertEqual([d[0] for d in r["divergent"]], ["IX", "XI"])

    def test_clause_files_match_principles(self):
        for column, name, n_clauses, readings in (
                ("m2", "clauses-m2.csv", 28, {None: 12, False: 11, True: 12}),
                ("m3", "clauses-m3.csv", 37, {None: 12, False: 10, True: 14})):
            clauses = conc.load_clauses(name)
            self.assertEqual(len(clauses), n_clauses, name)
            derived, _ = conc.classify(clauses)
            self.assertEqual(derived, {p["id"]: p[column] for p in self.principles}, name)
            for flag, covered in readings.items():
                self.assertEqual(conc.classify(clauses, flag)[1], covered, f"{name} reading {flag}")

    def test_stored_output_is_current(self):
        stored = (CASE / "concordance-output.txt").read_text(encoding="utf-8")
        self.assertEqual(conc.report(), stored,
                         "regenerate with: python3 case-study/concordance.py --write")

    def test_planted_violation_changes_the_statistics(self):
        planted = copy.deepcopy(self.principles)
        next(p for p in planted if p["id"] == "XI")["m3"] = "partial"
        r = conc.compare(planted, "m2", "m3", ["V", "XIII"])
        self.assertNotEqual((r["agree"], round(r["kappa"], 3), round(r["weighted_kappa"], 3)),
                            (10, 0.486, 0.611))


if __name__ == "__main__":
    unittest.main()
