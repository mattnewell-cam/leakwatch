"""Refresh per-leaker verdict blurbs against the current record (keeps the old wording where still accurate).

python -m scripts.refresh_summaries [--apply]
"""
import sys
from concurrent.futures import ThreadPoolExecutor

from leakwatch.common import DATA, MODEL_SMART, SITE, load_json, save_json
from leakwatch.llm import S, call_json, obj

SCHEMA = obj({"summary": S, "changed": {"type": "boolean"}})
SYS = """You maintain a 2-3 sentence neutral verdict on an X account that posts AI-lab leak claims, for a public
leaderboard. You get the current blurb plus the account's CURRENT record (stats, best calls, biggest misses, recent
pending claims). Keep the existing wording where it is still accurate; fix anything the current record contradicts or
no longer supports (e.g. a cited hit that isn't in the record). What they're reliable on, where they miss, caveats
(relays a lot, vague, good on X but not Y). No numbers that might go stale; no snark.
Refer to the account as "the account" or "they" - never he/she/his/her (most accounts are anonymous). changed=true if you edited."""


def main():
    leakers = load_json(SITE / "data" / "leakers.json")
    claims = {c["id"]: c for c in load_json(SITE / "data" / "claims.json")}
    profiles = load_json(DATA / "profiles.json", {})
    todo = [l for l in leakers if l.get("tracked") and l["stats"]["n_resolved"] >= 3]

    def one(l):
        s = l["stats"]
        fmt = lambda ids: "\n".join(f"- {claims[i]['date'][:10]} [{claims[i]['verdict']}] {claims[i]['claim'][:200]}"
                                    for i in ids if i in claims) or "(none)"
        pend = [c for c in claims.values() if c["handle"].lower() == l["handle"].lower() and c["verdict"] == "pending"]
        pend = sorted(pend, key=lambda c: c["date"])[-5:]
        user = (f"Account @{l['handle']} ({l['category']}). Bio: {l.get('bio', '')[:200]}\n"
                f"Current blurb: {(profiles.get(l['handle'].lower()) or {}).get('summary') or '(none)'}\n\n"
                f"Stats: accuracy {s['credibility']}, settled {s['n_resolved']} (hits {s['n_true'] + s['n_mostly_true']}, "
                f"partly {s['n_partly_true']}, misses {s['n_false']}), already-public rate {s['stale_rate']}, "
                f"coverage {s['coverage']}, vague rate {s['vague_rate']}, by lab {s['by_lab']}\n\n"
                f"Best calls:\n{fmt(l.get('best_hits', []))}\n\nBiggest misses:\n{fmt(l.get('worst_misses', []))}\n\n"
                f"Recent pending:\n" + "\n".join(f"- {c['claim'][:160]}" for c in pend))
        try:
            return l["handle"].lower(), call_json(MODEL_SMART, SYS, user, SCHEMA, name="blurb")
        except Exception as e:
            print("err", l["handle"], e)
            return l["handle"].lower(), None

    with ThreadPoolExecutor(8) as ex:
        res = dict(ex.map(one, todo))
    n = 0
    for h, r in res.items():
        if r and r["changed"]:
            n += 1
            print(f"\n@{h}\n  old: {(profiles.get(h) or {}).get('summary', '')[:260]}\n  new: {r['summary'][:260]}")
    print(f"\n{n} of {len(res)} changed")
    if "--apply" in sys.argv:
        for h, r in res.items():
            if r:
                profiles[h] = {"summary": r["summary"]}
        save_json(DATA / "profiles.json", profiles)


if __name__ == "__main__":
    main()
