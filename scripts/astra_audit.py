"""Blind second grading by GPT-6 Astra on a random sample of un-audited settled claims -> agreement stats.

python -m scripts.astra_audit N [seed] [--apply]
--apply: where Astra disagrees with the outcome bucket, adopt Astra's verdict and mark it audited.
"""
import random
import sys
from concurrent.futures import ThreadPoolExecutor

from leakwatch.common import DATA, load_json, now_iso, save_json
from leakwatch.resolve import resolve_batch
from leakwatch.scoring import VALUE, effective_verdict

BUCKET = {"true": "hit", "mostly_true": "hit", "partly_true": "partly", "false": "miss"}


def bucket(v):
    return BUCKET.get(v, "excluded")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(args[0]) if args else 20
    seed = int(args[1]) if len(args) > 1 else 1
    claims = load_json(DATA / "claims.json")
    accts = {a["handle"].lower(): a["category"] for a in load_json(DATA / "accounts.json")}
    pool = []
    for c in claims:
        c["_category"] = accts.get(c["handle"].lower())
        r = c.get("resolution") or {}
        if (not c.get("pruned") and r and not r.get("vetted") and not c.get("astra_checked")
                and r.get("verdict") not in ("pending", "not_a_claim")):
            pool.append(c)
    random.seed(seed)
    sample = random.sample(pool, min(n, len(pool)))
    batches = [sample[i:i + 5] for i in range(0, len(sample), 5)]
    out = {}
    with ThreadPoolExecutor(4) as ex:
        for r in ex.map(lambda b: _safe(b), batches):
            out.update(r)
    agree_b = agree_e = tot = 0
    rows = []
    for c in sample:
        a = out.get(c["id"])
        if not a:
            continue
        tot += 1
        lv = c["resolution"]["verdict"]
        agree_b += bucket(lv) == bucket(a["verdict"])
        agree_e += lv == a["verdict"]
        if bucket(lv) != bucket(a["verdict"]):
            rows.append((c, lv, a))
    print(f"Astra vs Luna on {tot}: bucket agreement {agree_b / max(tot, 1):.1%}, exact {agree_e / max(tot, 1):.1%}")
    for c, lv, a in rows[:15]:
        print(f"\n@{c['handle']} {c['date'][:10]} luna={lv} astra={a['verdict']} | {c['claim'][:110]}\n"
              f"   astra: {a['explanation'][:230]}")
    stats = load_json(DATA / "audit_stats.json", {}) or {}
    hist = stats.get("astra_samples", [])
    hist.append({"n": tot, "bucket": agree_b, "exact": agree_e, "at": now_iso()})
    stats["astra_samples"] = hist
    N = sum(h["n"] for h in hist)
    stats.update({"sample_n": N, "bucket_agreement": round(sum(h["bucket"] for h in hist) / N, 3),
                  "exact_agreement": round(sum(h["exact"] for h in hist) / N, 3), "auditor": "GPT-6 Astra",
                  "computed_at": now_iso()})
    if "--apply" in sys.argv:
        byid = {c["id"]: c for c in claims}
        for c in sample:
            a = out.get(c["id"])
            if not a:
                continue
            cc = byid[c["id"]]
            cc["astra_checked"] = True
            if bucket(a["verdict"]) != bucket(cc["resolution"]["verdict"]):
                old = cc["resolution"]["verdict"]
                a.pop("id", None)
                a["resolved_at"] = now_iso()
                a["vetted"] = {"by": "gpt-6-astra", "at": now_iso(), "changed_from": old, "note": a["explanation"]}
                cc["resolution"] = a
        for c in claims:
            c.pop("_category", None)
        save_json(DATA / "claims.json", claims)
        save_json(DATA / "audit_stats.json", stats)
        print("applied")


def _safe(b):
    try:
        return resolve_batch(b, "gpt-6-astra")
    except Exception as e:
        print("err", str(e)[:150])
        return {}


if __name__ == "__main__":
    main()
