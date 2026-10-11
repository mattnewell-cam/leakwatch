"""Re-check that each stored claim is really a leak claim, judging the TWEET itself (not the extracted summary).

python -m scripts.prune_claims [--sample N] [--apply]
Non-claims get c["pruned"] = reason (hidden from site + scores). Misstated summaries get corrected (old kept in
c["claim_v1"]); corrected claims lose their resolution so they get re-graded.
"""
import random
import sys
from concurrent.futures import ThreadPoolExecutor

from leakwatch.common import DATA, MODEL_SMART, load_json, save_json
from leakwatch.llm import B, S, arr, call_json, enum, obj
from leakwatch.resolve import _category

SCHEMA = obj({"items": arr(obj({
    "id": S,
    "is_leak_claim": B,
    "reason": S,
    "summary_ok": B,
    "corrected_claim": {"type": ["string", "null"]},
    "kind": enum("leak", "commentary", "reaction_to_public_news", "relay_of_named_source", "joke_or_vibes",
                 "general_prediction", "using_public_product", "quoting_official", "other_non_claim"),
}))})

SYS = """You audit a database of "leak claims" about AI labs extracted from X posts. Judge each POST ITSELF.

A leak claim = the post asserts NON-PUBLIC information (at posting time) that could later prove true or false: an
unreleased model/codename, release timing, unreleased features found in code or tests, capabilities of unreleased
models, internal events, upcoming deals/funding/IPOs/departures, government actions, etc. Cryptic teasers count if they
clearly point at a specific upcoming event.

NOT leak claims (is_leak_claim=false): opinions/commentary, reactions to something already launched, describing using a
public product, relaying a named published source ("per Bloomberg", "according to @x", linked article), quoting an
official announcement, jokes/vibes/hype with no specific content, generic predictions ("AGI by 2030", "progress is accelerating",
"models will keep getting better").
KEEP specific, checkable predictions about a named product/event/timing (e.g. "X ships before Y", "GPT-5 lands between
March and June", "Gemini 3.5 Pro was cancelled") - leakers often phrase leaks as predictions; these are scored later.

JOURNALISTS (account_type=journalist, bio given): a post sharing their OWN outlet's reporting IS a leak claim - their
own story, a co-written story ("story w/ @colleague"), or a colleague's scoop at the same outlet ("New from @reuters",
"breaking @theinformation", "@colleague reports"). Use the bio to know their outlet (they may have moved outlets over
the years). Only drop it if they clearly relay a DIFFERENT outlet's report.

You don't have web access: judge from the post text and its date. When unsure whether info was already public, keep it
(is_leak_claim=true) - novelty is checked later.

Also check the extracted summary: summary_ok=false if it misstates what the post says (adds things, calls public things
"unreleased", wrong dates, wrong lab). Then give corrected_claim: one standalone sentence stating what the post asserts
(state the asserted fact directly, e.g. "Google will release X on 2026-05-01" - not "the author said..."; keep the post's
hedges like "reportedly"/"may"), absolute dates. Only correct real misstatements, not wording preferences. IMPORTANT: one post often contains several distinct claims and each summary covers just ONE of them - judge only the claim this summary is about; never swap in a different claim from the same post, and keep every part of the summary the post supports. If the summary's claim is not in the post at all, set is_leak_claim=false (kind other_non_claim). Otherwise
corrected_claim=null. Most items need no correction."""


def fmt(c):
    tw = "\n".join(f"  POST ({t['created_at'][:10]}): {t['text'][:2000]}" + (
        f"\n    [quoting @{t['quoted'].get('handle')}: {t['quoted'].get('text', '')[:800]}]" if t.get("quoted") else "")
        for t in c.get("tweets", [])[:2])
    if not tw:
        tw = f"  DOCUMENTED QUOTE: {c.get('quote') or '(none - recovered from press: ' + str(c.get('source_url')) + ')'}"
    cat = _category(c["handle"])
    bio = f" bio: {_BIOS.get(c['handle'].lower(), '')[:200]}" if cat == "journalist" else ""
    return (f"id={c['id']} | @{c['handle']} (account_type={cat}{bio}) | {c['date'][:10]}\n{tw}\n"
            f"  EXTRACTED SUMMARY: {c['claim']}")


_BIOS = {a["handle"].lower(): (a.get("profile") or {}).get("bio") or "" for a in load_json(DATA / "accounts.json", [])}


def check(batch):
    try:
        out = call_json(MODEL_SMART, SYS, "\n\n".join(fmt(c) for c in batch), SCHEMA, name="prune")
        return {r["id"]: r for r in out["items"]}
    except Exception as e:
        print("err", str(e)[:200], flush=True)
        return {}


def main():
    claims = load_json(DATA / "claims.json")
    if "--reset" in sys.argv:
        for c in claims:
            c.pop("pruned", None)
            c.pop("prune_checked", None)
            c.pop("_needs_regrade", None)
            if c.get("claim_v1"):
                c["claim"] = c.pop("claim_v1")
    # the site covers the generative-AI era; older scoops (2015 Facebook, self-driving...) are out of scope
    for c in claims:
        if c["date"][:10] < "2022-06-01" and not c.get("pruned"):
            c["pruned"] = "out_of_scope: predates the generative-AI era this site covers"
            c["prune_checked"] = True
    # journalists are exempt: deciding "own outlet vs relay" from one post (with career moves) proved unreliable
    pool = [c for c in claims if not c.get("pruned") and not c.get("prune_checked")
            and _category(c["handle"]) != "journalist"]
    if "--sample" in sys.argv:
        random.seed(int(sys.argv[sys.argv.index("--sample") + 2]) if len(sys.argv) > sys.argv.index("--sample") + 2
                    and sys.argv[sys.argv.index("--sample") + 2].isdigit() else 1)
        pool = random.sample(pool, int(sys.argv[sys.argv.index("--sample") + 1]))
    batches = [pool[i:i + 20] for i in range(0, len(pool), 20)]
    res = {}
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(check, batches):
            res.update(r)
    byid = {c["id"]: c for c in claims}
    drop = fix = 0
    for i, r in res.items():
        c = byid.get(i)
        if not c:
            continue
        if not r["is_leak_claim"]:
            drop += 1
            print(f"DROP [{r['kind']}] @{c['handle']} {c['date'][:10]} | {c['claim'][:110]}\n      why: {r['reason'][:160]}")
        elif not r["summary_ok"] and r.get("corrected_claim"):
            fix += 1
            print(f"FIX  @{c['handle']} | {c['claim'][:110]}\n   -> {r['corrected_claim'][:160]}")
        if "--apply" in sys.argv:
            c["prune_checked"] = True
            if not r["is_leak_claim"]:
                c["pruned"] = f"{r['kind']}: {r['reason']}"
            elif not r["summary_ok"] and r.get("corrected_claim"):
                c["claim_v1"] = c["claim"]
                c["claim"] = r["corrected_claim"]
                if c.get("resolution") and not c["resolution"].get("vetted"):
                    c["_needs_regrade"] = True
    print(f"\nchecked {len(res)}: drop {drop}, fix {fix}")
    if "--apply" in sys.argv:
        save_json(DATA / "claims.json", claims)


if __name__ == "__main__":
    main()
