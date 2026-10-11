"""Pick the credibility prior strength that makes no-hindsight legitimacy best predict outcomes (Brier score).

Read-only. python -m scripts.tune_prior
"""
from collections import defaultdict

from leakwatch import scoring as sc
from leakwatch.common import DATA, load_json


def main():
    accts = {a["handle"].lower(): a for a in load_json(DATA / "accounts.json") if not a.get("skip")}
    claims = [c for c in load_json(DATA / "claims.json") if not c.get("pruned") and not c.get("repeat_of")
              and (c.get("resolution") or {}).get("verdict") != "not_a_claim"]
    by = defaultdict(list)
    for c in claims:
        c["_category"] = (accts.get(c["handle"].lower()) or {}).get("category")
        by[c["handle"].lower()].append(c)
    resolved = [c for c in claims if sc.effective_verdict(c) in sc.VALUE]
    print(f"{len(resolved)} settled claims")
    for k in (4, 6, 8, 12, 16, 24):
        sc.PRIOR_A = sc.PRIOR_B = k / 2
        sc.UNTRACKED_PRIOR = (sc.UNKNOWN_PRIOR * k, (1 - sc.UNKNOWN_PRIOR) * k)
        se, n, bins = 0.0, 0, defaultdict(lambda: [0, 0.0, 0.0])
        for c in resolved:
            p, _ = sc.legitimacy(c, by[c["handle"].lower()], tracked=c["handle"].lower() in accts)
            y = sc.VALUE[sc.effective_verdict(c)]
            se += (p / 100 - y) ** 2
            n += 1
            b = bins[min(9, p // 10)]
            b[0] += 1; b[1] += p / 100; b[2] += y
        top = [(f"{i * 10}s", v[0], round(v[1] / v[0], 2), round(v[2] / v[0], 2)) for i, v in sorted(bins.items())
               if i >= 7 and v[0]]
        print(f"prior strength {k:>2}: Brier {se / n:.4f}   top bands (n, mean score, observed) {top}")


if __name__ == "__main__":
    main()
