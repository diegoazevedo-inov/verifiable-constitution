"""Replays the defects planted by the fourth audit round (V1–V17, audits/rounds.csv) against a source tree.

Each defect is a text replacement in one source file. For each defect the tree is copied to a
temporary directory, the replacement is applied there (the original string must occur exactly once),
and the two CI steps are run in the copy:

    python -m unittest discover -s checks -t .
    python -m tools.coverage

A defect counts as caught when either step exits with a non-zero code. The replacements were
re-implemented from the descriptions in the audit report; the auditor's own scripts were not kept.

Usage:
    python3 audits/replay.py                 # replay against this repository
    python3 audits/replay.py --root PATH     # replay against another checkout (for example a tag)
Exit code 0 when every defect applies; the number caught is printed, not enforced.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WB = "example/workbench.py"
SESSION = "(SELECT tenant_id FROM session_tenant)"
WORDS = "(CONFIDENCE|SCORE|PROBABILITY|CERTAINTY|LIKELIHOOD)"
REGEX_LINE = 'CONFIDENCE_CODE = re.compile(r"(^|_)' + WORDS + '(_|$)")'
CONFIDENCE_RULE = '    if all(CONFIDENCE_CODE.search(item["code"]) for item in evidence):'
TRIM = "char(9, 10, 11, 12, 13)"

DEFECTS = [
    ("V1", "Insert-pending trigger without the status check", WB,
     "WHEN NEW.status IS NOT 'PENDING' OR NEW.decided_by IS NOT NULL", "WHEN NEW.decided_by IS NOT NULL"),
    ("V2", "Insert-pending trigger without the approver check", WB,
     "WHEN NEW.status IS NOT 'PENDING' OR NEW.decided_by IS NOT NULL", "WHEN NEW.status IS NOT 'PENDING'"),
    ("V3", "Decision trigger without the session-tenant check", WB,
     f"ON proposals\n  WHEN OLD.tenant_id IS NOT {SESSION}\n    OR NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.decided_by",
     "ON proposals\n  WHEN NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.decided_by"),
    ("V4", "Decision trigger without the approver check", WB,
     "\n    OR NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.decided_by AND tenant_id = OLD.tenant_id)", ""),
    ("V5", "Confidence refused only with one evidence item", WB,
     CONFIDENCE_RULE, CONFIDENCE_RULE.replace("if all(", "if len(evidence) == 1 and all(")),
    ("V6", "Confidence refused only up to two evidence items", WB,
     CONFIDENCE_RULE, CONFIDENCE_RULE.replace("if all(", "if len(evidence) <= 2 and all(")),
    ("V7", "Confidence pattern matches only the whole code", WB,
     REGEX_LINE, f'CONFIDENCE_CODE = re.compile(r"^{WORDS}$")'),
    ("V8", "Confidence pattern without the leading delimiter", WB,
     REGEX_LINE, f'CONFIDENCE_CODE = re.compile(r"{WORDS}(_|$)")'),
    ("V9", "Confidence pattern without the trailing delimiter", WB,
     REGEX_LINE, f'CONFIDENCE_CODE = re.compile(r"(^|_){WORDS}")'),
    ("V10", "Confidence pattern with word boundaries", WB,
     REGEX_LINE, f'CONFIDENCE_CODE = re.compile(r"\\b{WORDS}\\b")'),
    ("V11", "Evidence trigger trim without vertical tab and form feed", WB, TRIM, "char(9, 10, 13)"),
    ("V12", "Evidence trigger trim without carriage return", WB, TRIM, "char(9, 10, 11, 12)"),
    ("V13", "Evidence trigger trim without tab", WB, TRIM, "char(10, 11, 12, 13)"),
    ("V14", "PRAGMA recursive_triggers line removed from connect()", WB,
     '    conn.execute("PRAGMA recursive_triggers = ON")\n', ""),
    ("V15", "Work-item insert trigger without the session check", WB,
     f"BEFORE INSERT ON work_items\n  WHEN NEW.tenant_id IS NOT {SESSION}\n    OR ", "BEFORE INSERT ON work_items\n  WHEN "),
    ("V16", "User identity trigger without tenant", WB,
     "BEFORE UPDATE OF id, tenant_id ON users", "BEFORE UPDATE OF id ON users"),
    ("V17", "Service evidence check without str.strip()", WB,
     "(isinstance(value, str) and value.strip())", "(isinstance(value, str) and value)"),
]

STEPS = (("unittest", ["-m", "unittest", "discover", "-s", "checks", "-t", "."]),
         ("coverage", ["-m", "tools.coverage"]))


def copy_tree(source, target):
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".claude"))


def run_step(cwd, args):
    proc = subprocess.run([sys.executable, "-B", *args], cwd=cwd, capture_output=True, text=True, timeout=600)
    output = proc.stdout + proc.stderr
    if args[1] == "unittest":
        found = re.search(r"FAILED \(([^)]*)\)", output)
        detail = found.group(1) if found else "OK"
    else:
        detail = "traceback" if "Traceback" in output else ("blind detector" if "blind" in output else "table")
    return proc.returncode, detail


def replay(root):
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        copy_tree(root, base)
        baseline = [run_step(base, args) for _, args in STEPS]
        for defect_id, description, path, old, new in DEFECTS:
            work = Path(tmp) / defect_id
            copy_tree(base, work)
            target = work / path
            text = target.read_text(encoding="utf-8")
            occurrences = text.count(old)
            if occurrences != 1:
                rows.append((defect_id, description, None, None, f"not applicable ({occurrences} occurrences)"))
                continue
            target.write_text(text.replace(old, new), encoding="utf-8")
            results = [run_step(work, args) for _, args in STEPS]
            caught = any(code != 0 for code, _ in results)
            rows.append((defect_id, description, results[0], results[1], "caught" if caught else "NOT caught"))
            shutil.rmtree(work)
    return baseline, rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="source tree to replay against (default: this repository)")
    args = parser.parse_args(argv)
    baseline, rows = replay(args.root.resolve())
    print(f"Python {sys.version.split()[0]}")
    print("Baseline (no defect): " + "; ".join(f"{name} exit {code} ({detail})"
                                               for (name, _), (code, detail) in zip(STEPS, baseline)))
    print()
    print("| Defect | Description | unittest | coverage | Outcome |")
    print("|---|---|---|---|---|")
    for defect_id, description, unit, cov, outcome in rows:
        cell = lambda r: "—" if r is None else f"exit {r[0]} ({r[1]})"
        print(f"| {defect_id} | {description} | {cell(unit)} | {cell(cov)} | {outcome} |")
    applied = [r for r in rows if r[2] is not None]
    caught = [r for r in applied if r[4] == "caught"]
    print()
    print(f"Totals: {len(rows)} defects, {len(applied)} applied, {len(caught)} caught, {len(applied) - len(caught)} not caught.")
    return 0 if len(applied) == len(rows) and all(code == 0 for code, _ in baseline) else 1


if __name__ == "__main__":
    sys.exit(main())
