# Case study: three coverage measurements

Anonymised data of the case study in the accompanying manuscript: the per-principle and per-clause verification coverage of one system, measured three times, and the script that computes the agreement between assessors.

What this repository supports: the arithmetic (totals, raw agreement, kappa and weighted kappa) and the consistency between the clause files and the principle classes, both checked by `checks/test_case_study.py`. It does not support the classifications themselves, which are the author's transcription of the assessors' reports; neither the reports nor the measured code are included.

## The case

The case is a multi-tenant medical imaging platform under development by the author. Its source code is not public. Its constitution has 16 principles, each with a "Prohibits:" block, ordered in a four-tier conflict hierarchy (recipient safety; privacy and legal compliance; integrity of the source of truth; engineering discipline). The agentic part is small: one task in which a language model chooses an item from a closed list built by the system, with no effect until a human approves the proposal.

## Measurements

| Measurement | Commit | What it recorded |
|---|---|---|
| M1 | before the fixes | class per principle, read from its prohibitions; no clause decomposition was recorded |
| M2 | after the fixes (principles III, V, VII and X, and the review checklist) | 28 atomic clauses, coverage, reach, gate and detectors without a planted violation |
| M3 | a later commit with two follow-up fixes (V and XIII) | 37 atomic clauses, coverage, reach, gate, self-testing, strict and broad readings |

Commits are identified only as M1, M2 and M3.

Principles whose behaviour changed between two measured commits are marked in `principles.csv` (`behaviour_changed_m1_m2`, `behaviour_changed_m2_m3`) and left out of that comparison. According to the author, between M1 and M2 the fixes changed V, VII and X, and also III: the fix for X narrowed the guard that validates the model output, which is the verification of III, and placed the evaluation gate before any model call. Between M2 and M3 the follow-up fixes changed V and XIII.

How the measurements were made (author's account; it cannot be verified from this repository):

- Each measurement was carried out by an LLM agent session instructed with the written criterion below.
- The sessions only read the repository at a fixed commit. Nothing was written to the repository or to any database, and every count rests on a recorded command output.
- Each session worked without the earlier reports. M3 ran in a fresh session with no access to M1, M2, memory files or transcripts.
- The author reviewed the three reports. The data here transcribe their classifications; nothing was reclassified.

## Criterion

- A **clause** is atomic when it names one act on one kind of object. A "Prohibits:" block with "or" between distinct objects yields several clauses.
- A clause is **covered** when at least one automatic verification (test, static guard, database constraint or trigger, grant inventory, CI step) fails on the prohibited act and runs in a gate.
- A principle is **full** when all its clauses are covered, **partial** when at least one is, and **none** otherwise.
- **Reach** is `general` when the verification would catch a new instance of the act without being edited, and `instance` when it covers only existing paths.
- A clause is **borderline** when the assessor recorded that the classification depends on how the clause is read. The strict reading counts borderline clauses as not covered; the broad reading counts them as covered.
- A detector is **self-tested** when a test commits the prohibited act against it and requires rejection.

## Files

| File | Content |
|---|---|
| `principles.csv` | 16 rows, one per principle: the class of each principle in M1, M2 and M3, the input of the totals and of the agreement statistics |
| `clauses-m2.csv` | 28 rows, one per atomic clause of M2: reproduces the M2 principle classes and the covered-clause counts (as recorded, strict and broad readings) |
| `clauses-m3.csv` | 37 rows, one per atomic clause of M3: the same for M3 |
| `concordance.py` | Agreement statistics (Python standard library only); also checks that the clause files reproduce the principle classes |
| `concordance-output.txt` | Stored output of `concordance.py`: totals per measurement, the two agreement comparisons with their confusion matrices, and the clause-file cross-check |

`principles.csv` columns:

| Column | Values |
|---|---|
| `id` | I to XVI |
| `generic_name` | Generic English name of the principle |
| `tier` | `1_recipient_safety`, `2_privacy_legal_compliance`, `3_source_of_truth_integrity`, `4_engineering_discipline` |
| `status_report_declared` | What the project's own status report declared before M1: `complied`, `partial`, `not_yet` |
| `m1`, `m2`, `m3` | `full`, `partial`, `none` |
| `reach_m2`, `reach_m3` | Reach of the covered clauses: `general`, `instance`, `mixed` (some clauses general, others instance), `—` (no covered clause), `not_classified` (the assessor covered a clause without classifying its reach) |
| `behaviour_changed_m1_m2` | `yes` for the four principles whose behaviour changed between M1 and M2 (III, V, VII, X) |
| `behaviour_changed_m2_m3` | `yes` for the two principles whose code changed between M2 and M3 (V, XIII) |

Clause file columns:

| Column | Values |
|---|---|
| `principle`, `clause_id` | Principle and clause identifier as used by the assessor (`IV-a` in M2, `IV.1` in M3) |
| `prohibited_act` | Generic English paraphrase of the clause |
| `covered`, `borderline` | `yes` / `no` |
| `reach` | `general`, `instance`, `not_classified`, `—` |
| `gate` | `ci` (a CI step; the same detectors also ran in local hooks), `local_hook`, `none` |
| `detector_kind` | `db_constraint`, `db_trigger`, `db_grant_inventory`, `test`, `static_guard`, `ci_step`, `runtime_gate`; for uncovered clauses `review_only` (decidable only by review, as recorded by the assessor), `warning_only` (a check that prints a warning and never fails) or `none`. Several kinds are separated by `;` |
| `self_tested` | `yes` / `no` for covered clauses, `n.a.` for uncovered ones |

Conventions used when transcribing:

- `prohibited_act` paraphrases the original clause, written in another language, without product, tool, file, table or vendor names.
- `self_tested` is `yes` when the detectors on which the coverage rests have a planted violation of their own, as recorded by the assessor, and `no` when at least one of them has none (for example, the general-reach clauses rest on a database grant inventory and on static guards that read state without attempting the forbidden act).
- For the two uncovered borderline clauses of M3 (III.2, X.3), `gate` and `detector_kind` describe the verification that the broad reading would count.
- M3 recorded two clauses whose reach is borderline (VIII.3 and XIII.1): `instance` in the main reading, `general` in another. The file keeps the main reading; neither changes a principle class.
- M3 reported that four ambiguous blocks allow from 34 to 39 clauses; the ambiguous clauses are all uncovered, so only the denominator changes.
- Gate strength: in M3 the repository's hosting plan did not allow enforcing branch protection, so a failing CI step was not enforced as a merge block.

## Results reproduced

`concordance.py` compares only principles whose behaviour did not change between the two measured commits, reading the exclusions from `behaviour_changed_m1_m2` and `behaviour_changed_m2_m3`: M1 × M2 excludes III, V, VII and X, and M2 × M3 excludes V and XIII.

| Comparison | n | Raw agreement | Kappa | Weighted kappa (linear) |
|---|---|---|---|---|
| M1 × M2 | 12 | 10/12 | 0.667 | 0.769 |
| M2 × M3 | 14 | 10/14 | 0.486 | 0.611 |

Totals (full / partial / none): M1 2 / 6 / 8, M2 5 / 3 / 8, M3 3 / 3 / 10. Covered clauses: M2 12 of 28 (strict reading 11), M3 12 of 37 (strict 10, broad 14).

## Limitations

- Small n: 12 and 14 principles in three ordinal categories. The kappa values are unstable and are reported as a baseline, not as a property of the measure.
- The clause decomposition is manual. The same 16 blocks gave 28 clauses in M2 and 37 in M3.
- The assessors were LLM agent sessions, reviewed by the author. Human assessors might disagree differently.
- One system, built and fixed by the same author who designed the pattern.
- `tier`, `self_tested` and the generic names were transcribed or derived from the reports and the constitution by the author; they were not produced by the assessors in this form.

## Running

Python 3.12 (the version used by the CI workflow) and no third-party packages, from the repository root:

```bash
python3 case-study/concordance.py            # print the report
python3 case-study/concordance.py --write    # regenerate concordance-output.txt
python3 -m unittest checks.test_case_study   # check the numbers (also part of the CI suite)
```
