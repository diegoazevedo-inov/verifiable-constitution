"""Checks for the audit-round records (audits/): the per-round totals of the transcription, and the
agreement between the transcription of the fourth round and the stored replay outputs.

The replay itself (audits/replay.py) runs the full CI once per defect and is not part of this suite;
its outputs are stored in audits/ and checked here.
"""
import csv
import importlib.util
import re
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDITS = ROOT / "audits"


def load_rows():
    with open(AUDITS / "rounds.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_replay():
    spec = importlib.util.spec_from_file_location("replay", AUDITS / "replay.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stored_outcomes(name):
    text = (AUDITS / name).read_text(encoding="utf-8")
    rows = re.findall(r"^\| (V\d+) \|.*\| (caught|NOT caught) \|$", text, flags=re.M)
    totals = re.search(r"^Totals: (\d+) defects, (\d+) applied, (\d+) caught, (\d+) not caught\.$", text, flags=re.M)
    return dict(rows), tuple(int(n) for n in totals.groups())


class AuditRounds(unittest.TestCase):
    def setUp(self):
        self.rows = load_rows()

    def test_outcomes_are_from_the_closed_vocabulary(self):
        self.assertTrue(self.rows)
        for row in self.rows:
            self.assertIn(row["outcome"], {"caught", "not_caught", "equivalent"}, row)

    def test_totals_per_round(self):
        totals = {}
        for round_, outcomes in self._by_round().items():
            totals[round_] = (sum(outcomes.values()), outcomes["caught"], outcomes["equivalent"])
        self.assertEqual(totals, {"1": (8, 1, 0), "2": (19, 17, 1), "3": (18, 14, 0), "4": (17, 16, 0)})

    def test_defect_ids_are_unique_within_a_round(self):
        for round_ in {r["round"] for r in self.rows}:
            ids = [r["defect"] for r in self.rows if r["round"] == round_]
            self.assertEqual(len(ids), len(set(ids)), round_)

    def test_caught_means_a_failing_ci_step(self):
        for row in self.rows:
            failed = row["unittest"] != "pass" or row["coverage"] != "exit 0"
            self.assertEqual(failed, row["outcome"] == "caught", row)

    def _by_round(self):
        by_round = {}
        for row in self.rows:
            by_round.setdefault(row["round"], Counter())[row["outcome"]] += 1
        return by_round


class ReplayOfRoundFour(unittest.TestCase):
    def setUp(self):
        self.round4 = {r["defect"]: r["outcome"] for r in load_rows() if r["round"] == "4"}

    def test_replay_covers_exactly_the_defects_of_round_four(self):
        self.assertEqual([d[0] for d in load_replay().DEFECTS], list(self.round4))

    def test_replay_at_the_audited_code_matches_the_transcription(self):
        # v1.2 has the same code and tests as the audited commit; only two lines of case-study/README.md differ
        outcomes, totals = stored_outcomes("replay-output-v1.2.txt")
        expected = {d: ("caught" if o == "caught" else "NOT caught") for d, o in self.round4.items()}
        self.assertEqual(outcomes, expected)
        self.assertEqual(totals, (17, 17, 16, 1))

    def test_replay_at_this_version_catches_every_defect(self):
        outcomes, totals = stored_outcomes("replay-output.txt")
        self.assertEqual(set(outcomes), set(self.round4))
        self.assertEqual(set(outcomes.values()), {"caught"})
        self.assertEqual(totals, (17, 17, 17, 0))


if __name__ == "__main__":
    unittest.main()
