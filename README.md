# verifiable-constitution

A pattern for governing systems in which a language model proposes actions in a regulated domain: every principle is written as a prohibition, every prohibition is bound to an automatic check, and every check is shown to fail under a planted violation.

Writing principles down does not make them hold. A principle counts as **covered** only when:

1. a check exists that fails if the prohibited thing happens; and
2. every planted violation of it shows that check actually failing.

Coverage is reported per clause (full / partial / none) together with its **reach**: `general` when the check would also catch a new case (for example a database constraint or trigger), `instance` when it covers only the existing path. For a database guarantee, `general` means any INSERT, UPDATE, DELETE, REPLACE or UPSERT on a connection opened by the example's `connect()`; the constitution lists what lies outside that reach.

Reach is **declared** by the author in the constitution, not measured; `tools/coverage.py` copies it into its table. FULL means that every declared *Prohibits* clause of a principle is covered, not that the whole statement of the principle is. Parts of a statement without a clause in the example (external channels in C9, retention periods in C7, the time order in C10) are listed in the constitution under **Not measured** and printed by the tool.

## Contents

| Path | What it is |
|---|---|
| `constitution/constitution.md` | Generic template with ten principles (C1–C10), their *Prohibits* clauses, verifications and reach |
| `example/workbench.py` | Minimal proposal workbench (Python standard library + SQLite) that applies the template |
| `checks/test_constitution.py` | One or more checks per clause |
| `tools/mutants.py` | One or more planted violations per clause |
| `tools/coverage.py` | Runs each clause's checks against the example (must pass) and under each of its planted violations (must fail) and prints the coverage table |
| `checks/test_coverage_tool.py` | Self-test of the measuring tool: a no-op planted violation must be reported as a blind detector and make the tool exit with a non-zero code |
| `docs/adr/` | Decision records referenced by the example (checked by C10) |
| `case-study/` | Anonymised coverage measurements of one real system and the agreement script (see below) |

## Running

Python 3.12 (the version used by the CI workflow) and no third-party packages. The example needs an SQLite build with the JSON functions `json_valid` and `json_array_length` (built in by default since SQLite 3.38).

```bash
python3 -m unittest discover -s checks -t .   # checks against the example
python3 -m tools.coverage                      # coverage table; exit code 1 if any detector is blind
```

## The ten principles

C1 Deterministic core; the model only proposes · C2 The model chooses, it does not name · C3 No proposal without traceable evidence; confidence is not evidence · C4 Validation by a qualified professional · C5 Append-only trail, including reads and agent actions · C6 Tenant isolation enforced below the application · C7 Validated records are immutable; retention is a duty · C8 No agent task without a passing evaluation for the (model, prompt version) pair · C9 Model output and external channels are untrusted input · C10 Decision before code, traceable.

## Case study

`case-study/` holds the anonymised data of three coverage measurements of a multi-tenant medical imaging platform under development by the author: the class of each of its 16 principles in the three measurements, the clause-level classification of the second and third, and a script that reproduces the agreement between assessors (raw agreement, Cohen's kappa and linearly weighted kappa). `checks/test_case_study.py` checks those numbers in the same CI run. The repository supports the arithmetic and the consistency of these data, not the classifications themselves. See `case-study/README.md` for the method and its limitations.

## Limits

- The example is deliberately small. Tenant isolation is emulated with tenant-scoped views and triggers keyed to a session-tenant table set by the application; SQLite has no grants or roles, so a new read of a base table is not stopped, and the database guarantees do not hold against a schema change (dropping a trigger), a direct write to the session-tenant table or a connection with recursive triggers off. Production systems should rely on database row-level security and on a schema-owner role that the application does not hold.
- Coverage is ordinal and per clause. Two separate measurements of the same system can classify some clauses differently; a second rater is recommended.
- A check with `instance` reach does not protect a new path (a new task, a new endpoint). Record the reach next to the coverage.

## License

Apache License 2.0.
