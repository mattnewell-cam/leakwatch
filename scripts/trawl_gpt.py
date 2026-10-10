"""Find famous / deleted / pre-dataset leak claims for an account via GPT + web search. Does NOT judge outcomes."""
import sys
from concurrent.futures import ThreadPoolExecutor
from leakwatch.common import DATA, MODEL_SMART, load_json, save_json
from leakwatch.llm import S, arr, call_json, enum, obj

SCHEMA = obj({"claims": arr(obj({"date": S, "date_precision": enum("day", "week", "month"), "claim": S,
                                  "quote": {"type": ["string", "null"]}, "tweet_url": {"type": ["string", "null"]},
                                  "source_url": S, "deleted": {"type": ["boolean", "null"]}}))})
SYS = """Today is 2026-10-10. You research the public track record of X/Twitter accounts that post leaks about AI labs.
Use web search extensively (news articles quoting their tweets, Reddit threads, LessWrong, Manifold/Polymarket markets,
archive mentions). Find SPECIFIC, DATED leak claims by the given account that got attention - especially ones later
deleted, and ones from before {since}. Do NOT judge whether they came true. Record exactly what was claimed, with absolute
dates, and the URL of a real source documenting it (never invent URLs). 0-15 claims; precision over volume."""

def trawl(handle, aliases, since):
    names = " / ".join("@" + h for h in [handle] + aliases)
    out = call_json(MODEL_SMART, SYS.format(since=since), f"Account: {names}", SCHEMA, name="trawl", web_search=True, timeout=900)
    return out["claims"]

def main():
    accts = [a for a in load_json(DATA / "accounts.json") if not a.get("skip")]
    only = [x.lower() for x in sys.argv[1:]]
    if only: accts = [a for a in accts if a["handle"].lower() in only]
    def one(a):
        p = DATA / "cache" / "trawl" / f"{a['handle'].lower()}.json"
        if p.exists(): return
        raw = load_json(DATA / "raw" / f"{a['handle'].lower()}.json", {}) or {}
        since = raw["tweets"][0]["created_at"][:10] if raw.get("tweets") else "2026-10-10"
        try:
            c = trawl(a["handle"], a.get("aliases", []), since)
        except Exception as e:
            print("ERR", a["handle"], e, flush=True); return
        save_json(p, {"handle": a["handle"], "claims": c})
        print(a["handle"], len(c), flush=True)
    with ThreadPoolExecutor(6) as ex: list(ex.map(one, accts))

if __name__ == "__main__":
    main()
