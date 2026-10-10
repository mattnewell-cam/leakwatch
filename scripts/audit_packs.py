"""Build audit packs: per leaker, the verdicts that move their score most. Written for Claude reviewers."""
import sys
from leakwatch.common import DATA, load_json, save_json
from leakwatch import scoring as sc

PER_PACK = 5


def main():
    claims = load_json(DATA / "claims.json")
    accts = [a for a in load_json(DATA / "accounts.json") if not a.get("skip")]
    by = {}
    cats = {a["handle"].lower(): a["category"] for a in accts}
    for c in claims:
        c["_category"] = cats.get(c["handle"].lower())
        c["verdict"] = sc.effective_verdict(c)
        by.setdefault(c["handle"].lower(), []).append(c)
    leakers = []
    for a in accts:
        cl = by.get(a["handle"].lower(), [])
        if not cl:
            continue
        st = sc.leaker_stats(cl)
        pick = {}
        hits = sorted([c for c in cl if c["verdict"] in ("true", "mostly_true")],
                      key=lambda c: -(c["significance"] * c["specificity"] * sc.lead_factor(sc.lead_days(c))))
        misses = sorted([c for c in cl if c["verdict"] == "false"], key=lambda c: -(c["significance"] * c["specificity"]))
        partly = sorted([c for c in cl if c["verdict"] == "partly_true"], key=lambda c: -c["significance"])
        stale = sorted([c for c in cl if c["verdict"] == "already_public" and c["significance"] >= 4],
                       key=lambda c: -c["specificity"])
        for c in hits[:9] + misses[:6] + partly[:2] + stale[:3]:
            pick[c["id"]] = c
        items = []
        for c in pick.values():
            r = c.get("resolution") or {}
            items.append({"id": c["id"], "date": c["date"][:10], "claim": c["claim"], "lab": c["lab"],
                          "resolve_by": c.get("resolve_by"), "significance": c["significance"],
                          "tweet": " || ".join(t["text"][:500] for t in c.get("tweets", [])[:2]) or c.get("quote"),
                          "origin": c.get("origin"), "source_url": c.get("source_url"),
                          "resolver_verdict": r.get("verdict"), "public_date": r.get("public_date"),
                          "explanation": r.get("explanation"), "evidence": [e["url"] for e in r.get("evidence", [])],
                          "confidence": r.get("confidence")})
        leakers.append({"handle": a["handle"], "category": a["category"], "bio": (a.get("profile") or {}).get("bio"),
                        "stats": {k: st[k] for k in ("n_claims", "n_resolved", "n_true", "n_mostly_true", "n_partly_true",
                                                     "n_false", "n_pending", "n_already_public", "credibility",
                                                     "median_lead_days", "stale_rate", "vague_rate")},
                        "sample_pending": [c["claim"] for c in cl if c["verdict"] == "pending"][-5:],
                        "claims_to_audit": items})
    leakers.sort(key=lambda l: -len(l["claims_to_audit"]))
    # round-robin into packs so each pack has similar size
    n = max(1, (len(leakers) + PER_PACK - 1) // PER_PACK)
    packs = [[] for _ in range(n)]
    for i, l in enumerate(leakers):
        packs[i % n].append(l)
    for i, p in enumerate(packs):
        save_json(DATA / "cache" / "audit" / f"pack_{i}.json", {"leakers": p})
    print(n, "packs;", sum(len(l["claims_to_audit"]) for l in leakers), "claims to audit")


if __name__ == "__main__":
    main()
