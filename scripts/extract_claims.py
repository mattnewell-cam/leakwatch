"""Run LLM claim extraction over data/raw/*.json -> data/cache/claims_raw/<handle>.json"""
import sys
from concurrent.futures import ThreadPoolExecutor

from leakwatch.common import DATA, RAW, load_json, save_json
from leakwatch.extract import extract_all

OUT = DATA / "cache" / "claims_raw"


def run(handle, category, force=False):
    out = OUT / f"{handle.lower()}.json"
    if out.exists() and not force:
        return
    raw = load_json(RAW / f"{handle.lower()}.json")
    if not raw or not raw.get("tweets"):
        print(f"no tweets for {handle}")
        return
    tweets = raw["tweets"]
    claims = extract_all(raw["handle"], category, tweets)
    byid = {t["id"]: t for t in tweets}
    for c in claims:
        c["handle"] = raw["handle"]
        c["tweets"] = [byid[i] for i in c["tweet_ids"] if i in byid]
        c["date"] = min(t["created_at"] for t in c["tweets"])
    claims.sort(key=lambda c: c["date"])
    save_json(out, {"handle": raw["handle"], "n_tweets": len(tweets), "claims": claims})
    print(f"{raw['handle']}: {len(tweets)} tweets -> {len(claims)} claims", flush=True)


def main():
    force = "--force" in sys.argv
    only = [a.lower() for a in sys.argv[1:] if not a.startswith("--")]
    accts = load_json(DATA / "accounts.json")
    todo = [a for a in accts if (not only or a["handle"].lower() in only)
            and (RAW / f"{a['handle'].lower()}.json").exists()]
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(lambda a: run(a["handle"], a["category"], force), todo))


if __name__ == "__main__":
    main()
