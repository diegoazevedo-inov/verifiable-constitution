#!/usr/bin/env python3
"""Agreement between assessors of verification coverage (ordinal scale none < partial < full).

Reads principles.csv (one row per principle, classifications m1, m2, m3) and reproduces the
agreement statistics of the case study in the accompanying manuscript: raw agreement,
Cohen's kappa and linearly weighted kappa, computed only on the principles whose behaviour did not
change between the two measured commits. The exclusions are read from principles.csv:

  M1 x M2: behaviour_changed_m1_m2 = yes (III, V, VII, X)   -> 12 principles compared
  M2 x M3: behaviour_changed_m2_m3 = yes (V, XIII)          -> 14 principles compared

It also cross-checks the per-clause files: the principle classification derived from
clauses-m2.csv and clauses-m3.csv must equal the m2 and m3 columns of principles.csv.

Python standard library only.

Usage:
  python3 case-study/concordance.py            # print the report
  python3 case-study/concordance.py --write    # also write case-study/concordance-output.txt
"""
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCALE = ["none", "partial", "full"]


def load_principles(path=HERE / "principles.csv"):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def changed(principles, column):
    """Principles whose behaviour changed between two measured commits (column = yes); excluded from that comparison."""
    return [p["id"] for p in principles if p[column] == "yes"]


def load_clauses(name):
    with open(HERE / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def kappa(a, b, weights="none"):
    """Cohen's kappa for two raters on the ordinal scale; weights 'none' or 'linear' (|i-j|/(k-1))."""
    k, n = len(SCALE), len(a)
    obs = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        obs[x][y] += 1
    rows = [sum(obs[i]) for i in range(k)]
    cols = [sum(obs[i][j] for i in range(k)) for j in range(k)]

    def w(i, j):
        if weights == "linear":
            return abs(i - j) / (k - 1)
        return 0.0 if i == j else 1.0

    d_obs = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k)) / n
    d_exp = sum(w(i, j) * rows[i] * cols[j] for i in range(k) for j in range(k)) / (n * n)
    return 1 - d_obs / d_exp, obs, d_obs, d_exp


def compare(principles, first, second, excluded):
    rows = [p for p in principles if p["id"] not in excluded]
    a = [SCALE.index(p[first]) for p in rows]
    b = [SCALE.index(p[second]) for p in rows]
    k0, obs, _, _ = kappa(a, b)
    kl, _, d_obs, d_exp = kappa(a, b, "linear")
    return {
        "compared": [p["id"] for p in rows],
        "excluded": list(excluded),
        "agree": sum(x == y for x, y in zip(a, b)),
        "n": len(rows),
        "divergent": [(p["id"], p[first], p[second]) for p in rows if p[first] != p[second]],
        "matrix": obs,
        "kappa": k0,
        "weighted_kappa": kl,
        "d_obs": d_obs,
        "d_exp": d_exp,
    }


def totals(principles, column):
    return tuple(sum(1 for p in principles if p[column] == c) for c in ("full", "partial", "none"))


def classify(clauses, count_borderline=None):
    """Principle class from clauses. count_borderline: None = as recorded, False = strict, True = broad."""
    by_principle = {}
    for c in clauses:
        covered = c["covered"] == "yes"
        if c["borderline"] == "yes" and count_borderline is not None:
            covered = count_borderline
        by_principle.setdefault(c["principle"], []).append(covered)
    result = {}
    for pid, flags in by_principle.items():
        result[pid] = "full" if all(flags) else "partial" if any(flags) else "none"
    covered = sum(f for flags in by_principle.values() for f in flags)
    return result, covered


def report():
    principles = load_principles()
    out = []
    out.append(f"principles: {len(principles)}")
    for col in ("m1", "m2", "m3"):
        f, p, n = totals(principles, col)
        out.append(f"{col.upper()}: full {f} / partial {p} / none {n}")
    out.append("")

    for label, first, second, excluded in (("M2 x M3", "m2", "m3", changed(principles, "behaviour_changed_m2_m3")),
                                           ("M1 x M2", "m1", "m2", changed(principles, "behaviour_changed_m1_m2"))):
        r = compare(principles, first, second, excluded)
        out.append(f"== {label} ==")
        out.append(f"principles compared (n={r['n']}): {' '.join(r['compared'])}  (excluded: {' '.join(r['excluded'])})")
        out.append(f"raw agreement: {r['agree']}/{r['n']} = {r['agree'] / r['n']:.3f}")
        out.append("divergent: " + (", ".join(f"{pid} ({x} x {y})" for pid, x, y in r["divergent"]) or "none"))
        out.append("matrix (rows = first assessor, columns = second; order none, partial, full):")
        for i, name in enumerate(SCALE):
            out.append(f"    {name.ljust(8)} {r['matrix'][i]}")
        out.append(f"Cohen's kappa (unweighted): {r['kappa']:.3f}")
        out.append(f"Cohen's kappa (linear weights): {r['weighted_kappa']:.3f}  "
                   f"(observed disagreement {r['d_obs']:.4f}, expected {r['d_exp']:.4f})")
        out.append("")

    out.append("== Clause files ==")
    for col, name in (("m2", "clauses-m2.csv"), ("m3", "clauses-m3.csv")):
        clauses = load_clauses(name)
        derived, covered = classify(clauses)
        mismatches = [p["id"] for p in principles if derived.get(p["id"]) != p[col]]
        line = f"{name}: {len(clauses)} clauses, {covered} covered; derived classes match principles.csv: "
        out.append(line + ("yes" if not mismatches else "NO (" + " ".join(mismatches) + ")"))
        for reading, flag in (("strict", False), ("broad", True)):
            d, cov = classify(clauses, flag)
            f = sum(v == "full" for v in d.values())
            p = sum(v == "partial" for v in d.values())
            n = sum(v == "none" for v in d.values())
            out.append(f"    {reading} reading (borderline clauses {'covered' if flag else 'not covered'}): "
                       f"{cov} of {len(clauses)} clauses; full {f} / partial {p} / none {n}")
    out.append("")
    out.append("Caveat: small n (14 and 12 principles, 3 categories); values are unstable, "
               "with no useful confidence interval.")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    text = report()
    sys.stdout.write(text)
    if "--write" in sys.argv[1:]:
        (HERE / "concordance-output.txt").write_text(text, encoding="utf-8")
