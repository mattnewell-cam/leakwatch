"""Compute scores and write site/data/{claims,leakers,meta}.json from data/claims.json."""
import json
from collections import defaultdict

from leakwatch.common import DATA, SITE, load_json, now_iso
from leakwatch import scoring as sc
from leakwatch.resolve import deadline_stated

MIN_RESOLVED = 5
REPO_URL = "https://github.com/mattnewell-cam/leakwatch"


def main():
    all_accounts = load_json(DATA / "accounts.json", [])
    accounts = {a["handle"].lower(): a for a in all_accounts if not a.get("skip")}
    skipped = {a["handle"].lower() for a in all_accounts if a.get("skip")}
    claims = [c for c in load_json(DATA / "claims.json", []) if c["handle"].lower() not in skipped
              and not c.get("pruned") and (c.get("resolution") or {}).get("verdict") != "not_a_claim"]
    profiles = load_json(DATA / "profiles.json", {})  # handle -> {summary}
    newcomers = load_json(DATA / "newcomers.json", {})
    by_handle = defaultdict(list)
    for c in claims:
        c["_category"] = (accounts.get(c["handle"].lower()) or {}).get("category")
        c["verdict"] = sc.effective_verdict(c)
        c["lead_days"] = sc.lead_days(c)
        c["lead_ref_date"], c["lead_ref_kind"] = sc.lead_ref(c) if c["lead_days"] is not None else (None, None)
        if not c.get("repeat_of"):            # a leaker repeating their own claim is scored once
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
        st = sc.leaker_stats(cl, tracked=bool(acct))
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
    # journalists play a different game (institutional sourcing) - rank them separately
    for grp in ("journalists", "leakers"):
        members = [l for l in ranked if (l["category"] == "journalist") == (grp == "journalists")]
        for i, l in enumerate(members):
            l["rank"] = i + 1
            l["group"] = grp
    for l in leakers:
        l.setdefault("group", "journalists" if l["category"] == "journalist" else "leakers")
    leakers.sort(key=lambda l: (l.get("rank") or 9999, -l["stats"]["n_claims"]))

    # legitimacy, no hindsight
    cal = defaultdict(lambda: [0, 0.0, 0.0])
    for c in claims:
        h = c["handle"].lower()
        corro = 0.0
        if c.get("story_id") and c.get("source_type") != "relayed":
            # one vote per distinct tracked account that made the same claim no later than this one
            hs = sorted({o["handle"] for o in story[c["story_id"]] if o["handle"].lower() != h
                         and o["date"] <= c["date"] and o["handle"].lower() in accounts})
            if hs:
                # only corroborators with an above-average record add anything; echoes from weak sources add nothing
                cr = [sc.credibility_as_of(by_handle[x.lower()], c["date"][:10])[0] for x in hs]
                corro = min(0.10, 0.25 * sum(max(0.0, x - 0.5) for x in cr))
                c["corroborated_by"] = hs
        score, comps = sc.legitimacy(c, by_handle[h], tracked=h in accounts, corroboration=corro,
                                     plausibility=c.get("plausibility"))
        c["legitimacy"] = {"score": score, "components": comps}
        if c["verdict"] in sc.VALUE:
            b = min(9, score // 10)
            cal[b][0] += 1
            cal[b][1] += sc.VALUE[c["verdict"]]
            cal[b][2] += score
    calibration = []
    for b in range(10):
        n, s, ps = cal.get(b, [0, 0, 0])
        if n >= 8:
            # compare against the mean score actually given in the band, not the band midpoint
            calibration.append({"lo": b * 10, "hi": b * 10 + 10, "mid": round(ps / n, 1), "n": n,
                                "rate": round(s / n, 3)})

    out_claims = []
    for c in claims:
        o = {k: c.get(k) for k in ("id", "handle", "date", "claim", "lab", "topic", "specificity", "significance",
                                   "resolve_by", "hedged", "source_type", "cryptic", "origin", "verdict", "lead_days",
                                   "legitimacy", "first_seen", "feed_date", "corroborated_by", "quote", "source_url",
                                   "deleted", "repeat_of", "lead_ref_date", "lead_ref_kind")}
        if not deadline_stated(c):
            o.pop("resolve_by", None)   # default review horizon, not a date the leaker gave - don't show it
        o["tweets"] = [{k: t.get(k) for k in ("id", "url", "created_at", "text", "likes", "quoted")} for t in c.get("tweets", [])[:3]]
        r = c.get("resolution") or {}
        o["resolution"] = {k: r.get(k) for k in ("explanation", "evidence", "public_date", "official_date", "confidence", "vetted")} if r else None
        out_claims.append({k: v for k, v in o.items() if v not in (None, [], "")})

    n_res = sum(1 for c in claims if c["verdict"] in sc.VALUE)
    meta = {"updated_at": now_iso(), "n_claims": len(claims), "n_resolved": n_res,
            "n_pending": sum(1 for c in claims if c["verdict"] == "pending"),
            "n_leakers": sum(1 for l in leakers if l["tracked"]), "n_events": len(load_json(DATA / "events.json", [])),
            "min_resolved_for_rank": MIN_RESOLVED, "impact_k": sc.IMPACT_K, "calibration": calibration,
            "repo_url": REPO_URL, "audit": load_json(DATA / "audit_stats.json", None),
            "n_audited": sum(1 for c in claims if (c.get("resolution") or {}).get("vetted"))}
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    for name, obj in (("claims", out_claims), ("leakers", leakers), ("meta", meta)):
        (SITE / "data" / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
                                                    encoding="utf-8")
    print(f"site data: {len(out_claims)} claims, {len(leakers)} leakers, {len(ranked)} ranked, calib bins {len(calibration)}")


if __name__ == "__main__":
    main()
