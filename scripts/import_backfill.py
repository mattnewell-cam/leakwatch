"""Merge extracted tweet claims + trawled (press/archive) claims into data/claims.json.

- keeps any existing resolutions
- filters to AI-related claims (cheap LLM pass)
- de-duplicates repeated claims by the same leaker
"""
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from leakwatch.common import DATA, MODEL_FAST, load_json, now_iso, save_json
from leakwatch.extract import LABS, TOPICS, scope_filter
from leakwatch.llm import B, I, S, arr, call_json, enum, obj

STOP = set("the a an of to in on and or is was will be by for with that this as at it its from has have had are about "
           "reportedly said says would could may might new model models".split())


def toks(s):
    return {w for w in re.findall(r"[a-z0-9.\-]+", s.lower()) if w not in STOP and len(w) > 1}


def jacc(a, b):
    return len(a & b) / max(1, len(a | b))


def dedupe(claims):
    """Merge near-identical claims by the same leaker within 21 days."""
    claims = sorted(claims, key=lambda c: c["date"])
    kept = []
    recent = {}
    for c in claims:
        t = toks(c["claim"])
        key = (c["handle"].lower(), c["lab"])
        dup = None
        for k in recent.get(key, []):
            dd = (date.fromisoformat(c["date"][:10]) - date.fromisoformat(k["date"][:10])).days
            if dd <= 21 and jacc(t, k["_t"]) >= 0.5:
                dup = k
                break
        if dup:
            have = {x["id"] for x in dup["tweets"]}
            dup["tweets"] += [x for x in c["tweets"] if x["id"] not in have]
            dup["specificity"] = max(dup["specificity"], c["specificity"])
            continue
        c["_t"] = t
        recent.setdefault(key, []).append(c)
        kept.append(c)
    for c in kept:
        c.pop("_t", None)
    return kept


NORM_SCHEMA = obj({"items": arr(obj({"i": I, "lab": enum(*LABS), "topic": enum(*TOPICS), "specificity": I,
                                      "significance": I, "resolve_by": {"type": ["string", "null"]}, "hedged": B,
                                      "source_type": enum("insider", "code_or_testing_evidence", "journalism",
                                                          "relayed", "speculation"),
                                      "cryptic": B, "is_claim": B}))})
NORM_SYS = """For each documented leak claim, fill the fields. is_claim=false if it is not actually an assertion of
non-public info by that account (e.g. it describes others discussing them, or is commentary). specificity 1-5,
significance 1-5 (5 = frontier flagship release / industry-shaking event). resolve_by: YYYY-MM-DD by which it should have
happened (stated timing, else claim date + 180d) or null if unfalsifiable."""


def normalize_trawl(handle, items):
    if not items:
        return []
    txt = "\n".join(f"{i}: ({it['date']}) {it['claim']}" for i, it in enumerate(items))
    try:
        res = call_json(MODEL_FAST, NORM_SYS, f"Account @{handle}\n{txt}", NORM_SCHEMA, name="norm")["items"]
    except Exception as e:
        print("norm err", handle, e)
        return []
    out = []
    for r in res:
        if not r["is_claim"] or r["i"] >= len(items):
            continue
        it = items[r["i"]]
        dt = it["date"] if re.match(r"\d{4}-\d{2}-\d{2}", it["date"] or "") else None
        if not dt:
            continue
        h = hashlib.sha1((handle + it["claim"]).encode()).hexdigest()[:10]
        tw = []
        m = re.search(r"status/(\d+)", it.get("tweet_url") or "")
        if it.get("quote") and m:
            tw = [{"id": m.group(1), "url": it["tweet_url"], "created_at": dt + "T00:00:00Z", "text": it["quote"],
                   "likes": 0}]
        out.append({"id": f"{handle.lower()}-a{h}", "handle": handle, "date": dt + "T00:00:00Z", "claim": it["claim"],
                    "lab": r["lab"], "topic": r["topic"], "specificity": max(1, min(5, r["specificity"])),
                    "significance": max(1, min(5, r["significance"])), "resolve_by": r["resolve_by"],
                    "hedged": r["hedged"], "source_type": r["source_type"], "cryptic": r["cryptic"],
                    "tweets": tw, "quote": it.get("quote"), "source_url": it.get("source_url"),
                    "deleted": it.get("deleted"), "origin": "trawl", "date_precision": it.get("date_precision")})
    return out


def slim_tweet(t):
    return {"id": t["id"], "url": t["url"], "created_at": t["created_at"], "text": t["text"][:1200],
            "likes": t.get("likes", 0), "quoted": t.get("quoted")}


def main():
    accts = {a["handle"].lower(): a for a in load_json(DATA / "accounts.json") if not a.get("skip")}
    existing = {c["id"]: c for c in load_json(DATA / "claims.json", [])}
    new = []
    for h in accts:
        raw = load_json(DATA / "cache" / "claims_raw" / f"{h}.json")
        if not raw:
            continue
        seen = set()
        for c in raw["claims"]:
            cid = f"{h}-{c['tweet_ids'][0]}"
            k = 2
            while cid in seen:
                cid = f"{h}-{c['tweet_ids'][0]}-{k}"; k += 1
            seen.add(cid)
            if cid in existing:
                continue
            new.append({"id": cid, "handle": raw["handle"], "date": c["date"], "claim": c["claim"], "lab": c["lab"],
                        "topic": c["topic"], "specificity": c["specificity"], "significance": c["significance"],
                        "resolve_by": c["resolve_by"], "hedged": c["hedged"], "source_type": c["source_type"],
                        "cryptic": c["cryptic"], "tweets": [slim_tweet(t) for t in c["tweets"]], "origin": "tweet"})
    print("new tweet claims", len(new))
    new = dedupe(new)
    print("after dedupe", len(new))
    # trawled claims
    trawled = []

    def tr(h):
        d = load_json(DATA / "cache" / "trawl" / f"{h}.json")
        return normalize_trawl(d["handle"], d["claims"]) if d else []
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(tr, list(accts)):
            trawled += r
    # drop trawled claims that duplicate tweet claims we already have
    pool = new + list(existing.values())
    byh = {}
    for c in pool:
        byh.setdefault(c["handle"].lower(), []).append((toks(c["claim"]), c["date"][:10]))
    tk = []
    for c in trawled:
        if c["id"] in existing:
            continue
        t = toks(c["claim"])
        if any(jacc(t, t2) >= 0.45 and abs((date.fromisoformat(d2) - date.fromisoformat(c["date"][:10])).days) <= 10
               for t2, d2 in byh.get(c["handle"].lower(), [])):
            continue
        tk.append(c)
    print("trawled", len(trawled), "kept", len(tk))
    new = scope_filter(new + tk)
    print("in scope", len(new))
    for c in new:
        c["imported_at"] = now_iso()
        existing[c["id"]] = c
    allc = sorted(existing.values(), key=lambda c: c["date"])
    save_json(DATA / "claims.json", allc)
    print("total claims", len(allc))


if __name__ == "__main__":
    main()
