"""Compute scores and write site/data/{claims,leakers,meta}.json from data/claims.json."""
import json
from collections import defaultdict

from leakwatch.common import DATA, SITE, load_json, now_iso
from leakwatch import scoring as sc

MIN_RESOLVED = 5
REPO_URL = "https://github.com/mattnewell-cam/leakwatch"


def main():
    claims = load_json(DATA / "claims.json", [])
    accounts = {a["handle"].lower(): a for a in load_json(DATA / "accounts.json", []) if not a.get("skip")}
    profiles = load_json(DATA / "profiles.json", {})  # handle -> {summary}
    newcomers = load_json(DATA / "newcomers.json", {})
    by_handle = defaultdict(list)
    for c in claims:
        c["_category"] = (accounts.get(c["handle"].lower()) or {}).get("category")
        c["verdict"] = sc.effective_verdict(c)
        c["lead_days"] = sc.lead_days(c)
        by_handle[c["handle"].lower()].append(c)

    # corroboration index for pending claims: story ids assigned by the daily pipeline
    story = defaultdict(list)
    for c in claims:
        if c.get("story_id"):
            story[c["story_id"]].append(c)

    leakers = []
    for h, cl in by_handle.items():
        acct = accounts.get(h)
        info = {}
        prof = (acct or {}).get("profile") or newcomers.get(h) or {}
        st = sc.leaker_stats(cl)
        resolved = sorted([c for c in cl if c["verdict"] in sc.VALUE], key=lambda c: c["date"])
        good = [c for c in resolved if sc.VALUE[c["verdict"]] >= 0.8]
        best = sorted(good, key=lambda c: -(c["significance"] * sc.lead_factor(c["lead_days"]) * c["specificity"]))[:5]
        worst = sorted([c for c in resolved if c["verdict"] == "false"],
                       key=lambda c: -(c["significance"] * c["specificity"]))[:5]
        leakers.append({
            "handle": (acct or {}).get("handle") or cl[0]["handle"],
            "name": prof.get("name") or cl[0]["handle"],
            "avatar": prof.get("avatar"),
            "bio": prof.get("bio") or "",
            "followers": prof.get("followers"),
            "category": (acct or {}).get("category", "newcomer"),
            "aliases": (acct or {}).get("aliases", []),
            "tracked": bool(acct),
            "stats": st,
            "record": [c["verdict"] for c in resolved],
            "best_hits": [c["id"] for c in best],
            "worst_misses": [c["id"] for c in worst],
            "summary": (profiles.get(h) or {}).get("summary"),
        })
    ranked = sorted([l for l in leakers if l["stats"]["n_resolved"] >= MIN_RESOLVED and l["tracked"]],
                    key=lambda l: -l["stats"]["leak_score"])
    for i, l in enumerate(ranked):
        l["rank"] = i + 1
    leakers.sort(key=lambda l: (l.get("rank") or 9999, -l["stats"]["n_claims"]))

    # legitimacy, no hindsight
    cal = defaultdict(lambda: [0, 0.0])
    for c in claims:
        h = c["handle"].lower()
        corro = 0.0
        if c.get("story_id"):
            others = [o for o in story[c["story_id"]] if o["handle"].lower() != h and o["date"] <= c["date"]]
            if others:
                cr = [sc.credibility_as_of(by_handle[o["handle"].lower()], c["date"][:10])[0] for o in others]
                corro = min(0.15, 0.1 * sum(max(0, x - 0.4) for x in cr) + 0.03 * len(others))
                c["corroborated_by"] = sorted({o["handle"] for o in others})
        score, comps = sc.legitimacy(c, by_handle[h], tracked=h in accounts, corroboration=corro,
                                     plausibility=c.get("plausibility"))
        c["legitimacy"] = {"score": score, "components": comps}
        if c["verdict"] in sc.VALUE:
            b = min(9, score // 10)
            cal[b][0] += 1
            cal[b][1] += sc.VALUE[c["verdict"]]
    calibration = []
    for b in range(10):
        n, s = cal.get(b, [0, 0])
        if n >= 8:
            calibration.append({"lo": b * 10, "hi": b * 10 + 10, "mid": b * 10 + 5, "n": n, "rate": round(s / n, 3)})

    out_claims = []
    for c in claims:
        o = {k: c.get(k) for k in ("id", "handle", "date", "claim", "lab", "topic", "specificity", "significance",
                                   "resolve_by", "hedged", "source_type", "cryptic", "origin", "verdict", "lead_days",
                                   "legitimacy", "first_seen", "feed_date", "corroborated_by", "quote", "source_url",
                                   "deleted")}
        o["tweets"] = [{k: t.get(k) for k in ("id", "url", "created_at", "text", "likes")} for t in c.get("tweets", [])[:3]]
        r = c.get("resolution") or {}
        o["resolution"] = {k: r.get(k) for k in ("explanation", "evidence", "public_date", "confidence", "vetted")} if r else None
        out_claims.append({k: v for k, v in o.items() if v not in (None, [], "")})

    n_res = sum(1 for c in claims if c["verdict"] in sc.VALUE)
    meta = {"updated_at": now_iso(), "n_claims": len(claims), "n_resolved": n_res,
            "n_pending": sum(1 for c in claims if c["verdict"] == "pending"),
            "n_leakers": sum(1 for l in leakers if l["tracked"]), "n_events": len(load_json(DATA / "events.json", [])),
            "min_resolved_for_rank": MIN_RESOLVED, "impact_k": sc.IMPACT_K, "calibration": calibration,
            "repo_url": REPO_URL}
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    for name, obj in (("claims", out_claims), ("leakers", leakers), ("meta", meta)):
        (SITE / "data" / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
                                                    encoding="utf-8")
    print(f"site data: {len(out_claims)} claims, {len(leakers)} leakers, {len(ranked)} ranked, calib bins {len(calibration)}")


if __name__ == "__main__":
    main()
