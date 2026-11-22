# Audit rounds: defects planted against the detectors

Before its first publication (rounds 1 to 3) and before the v1.2 release (round 4), the repository was audited in four rounds, each run in a fresh session that had not written the code it audited (author's account; the session arrangement cannot be verified from this repository). Each round planted its own defects in copies of the repository, chosen and implemented by the auditor (some coincide in behaviour with planted violations already in `tools/mutants.py`), and ran the two CI steps on each copy:

```bash
python -m unittest discover -s checks -t .
python -m tools.coverage
```

A defect counts as **caught** when either step exits with a non-zero code, **not caught** when both pass, and **equivalent** when the auditor showed that the defect cannot change behaviour (another guarantee blocks its effect).

| Round | Audited commit | Planted | Caught | Equivalent | Not caught |
|---|---|---|---|---|---|
| 1 | `f5517df` | 8 | 1 | 0 | 7 |
| 2 | `3531aef` | 19 | 17 | 1 | 1 |
| 3 | `2d73551` | 18 | 14 | 0 | 4 |
| 4 | `44db3d2` | 17 | 16 | 0 | 1 |

Every defect that was not caught led to a fix in a later version (the next audited commit for rounds 1 and 2, v1.2 for round 3, v1.3 for round 4): a new test, trigger or planted violation, or a narrower statement of reach in the constitution. The round-4 gap (V17) is closed in v1.3 by `test_c3_service_rejects_whitespace_only_value` and its planted violation.

## Files

| File | What it is |
|---|---|
| `rounds.csv` | Transcription of the four audit reports: one row per planted defect, with the result of each CI step and the outcome |
| `replay.py` | Re-plants the 17 defects of round 4 in copies of a source tree and runs the two CI steps on each |
| `replay-output-v1.2.txt` | Output of `replay.py` against v1.2 (same code and tests as the commit audited in round 4): 16 of 17 caught, V17 not caught |
| `replay-output.txt` | Output of `replay.py` against this version: 17 of 17 caught |

`checks/test_audits.py` checks the per-round totals of `rounds.csv`, and that the stored replay outputs agree with the round-4 rows of the transcription.

## What can and cannot be verified here

- **Rounds 1 to 3 (author's account; it cannot be verified from this repository).** The audited commits were made before publication and are not in the public history, which was rewritten before the first release. The audit reports are not included. `rounds.csv` is the author's transcription of their defect tables.
- **Round 4 (reproducible).** The audited commit differs from v1.2 only in two lines of `case-study/README.md`; code, tests and planted violations are identical. It was amended into v1.2 before the push and is not in the public history. `replay.py` re-implements the 17 defects from the descriptions in the report, since the auditor's scripts were not kept, and its output against v1.2 reproduces the reported outcome. Failure counts can differ from the report, which named the failing clause in most rows; the replay also counts the coverage tool's self-test (for example, V7 and V10 break three C3.b tests and the self-test).

To replay against v1.2 from a clone of the public repository, where the tag exists:

```bash
git worktree add --detach /tmp/vc-v1.2 v1.2
python3 audits/replay.py --root /tmp/vc-v1.2
git worktree remove /tmp/vc-v1.2
```

To refresh a stored output, write it to another path first and then move it into `audits/`: the copies made by the replay include `audits/`, and `checks/test_audits.py` reads the stored outputs.
