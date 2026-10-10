"""Fetch each tracked account's historical, lab-related, high-engagement tweets.

Usage: python -m scripts.backfill_fetch handle1 handle2 ...   (or no args = all in data/accounts.json)
Writes data/raw/<handle>.json. Skips handles already fetched unless --force.
"""
import sys

from leakwatch.common import DATA, RAW, load_json, save_json, now_iso
from leakwatch.twitter import TwitterAPI

KEYWORDS = ("openai OR anthropic OR gemini OR deepmind OR google OR claude OR gpt OR grok OR xai OR llama "
            "OR meta OR deepseek OR qwen OR mistral OR model OR models OR release OR launch OR leak OR leaks "
            "OR hearing OR heard OR soon OR weeks OR internal OR internally OR agi OR o1 OR o3 OR o4 OR sora OR orion "
            "OR strawberry OR opus OR sonnet OR haiku OR ipo OR valuation OR raising OR ship OR shipping OR announce "
            "OR rumor OR rumour OR sources OR \"next week\" OR tomorrow OR imminent OR nvidia OR microsoft OR apple "
            "OR codex OR agent OR agents OR reasoning OR benchmark OR arena OR lmarena OR sama OR altman OR amodei "
            "OR hassabis OR musk OR zuck OR testing OR spotted OR found OR code OR string OR strings")

MAX_PER_ACCOUNT = 600
DEEP_MAX = 250


def min_faves_for(followers):
    return int(min(300, max(10, followers / 1000)))


def deep_history(api, user, mf, tweets):
    """Main query is newest-first and capped; reach further back with a higher like threshold."""
    main = [t for t in tweets if not t["is_reply"]]
    if len(main) < MAX_PER_ACCOUNT - 20:
        return []
    from datetime import datetime
    oldest = min(t["created_at"] for t in main)
    ts = int(datetime.strptime(oldest, "%Y-%m-%dT%H:%M:%SZ").timestamp())
    q = f"from:{user} min_faves:{mf * 3} -filter:replies until_time:{ts}"
    return list(api.search(q, "Latest", max_tweets=DEEP_MAX))


def deepen(api, handle):
    out = RAW / f"{handle.lower()}.json"
    d = load_json(out)
    if not d or d.get("deep_done") or not d.get("tweets"):
        return
    extra = deep_history(api, d["handle"], d["min_faves"], d["tweets"])
    ids = {t["id"] for t in d["tweets"]}
    d["tweets"] = sorted(d["tweets"] + [t for t in extra if t["id"] not in ids], key=lambda t: t["created_at"])
    d["deep_done"] = True
    save_json(out, d)
    print(f"{handle}: deep +{len(extra)} -> oldest {d['tweets'][0]['created_at'][:10]} credits={api.credits_used}", flush=True)


def fetch(api, handle, force=False):
    out = RAW / f"{handle.lower()}.json"
    if out.exists() and not force:
        print(f"skip {handle} (exists)")
        return
    info = api.user_info(handle)
    if not info or info.get("unavailable") or not info.get("userName"):
        print(f"!! {handle}: not found / unavailable: {str(info)[:200]}")
        save_json(out, {"handle": handle, "error": "unavailable", "info": info, "tweets": []})
        return
    followers = info.get("followers", 0)
    mf = min_faves_for(followers)
    q = f"from:{info['userName']} min_faves:{mf} -filter:replies"
    tweets = list(api.search(q, "Latest", max_tweets=MAX_PER_ACCOUNT))
    # Also grab their replies that got real traction - leakers often drop claims in replies.
    q2 = f"from:{info['userName']} min_faves:{mf * 3} filter:replies"
    tweets += list(api.search(q2, "Latest", max_tweets=80))
    tweets += deep_history(api, info["userName"], mf, tweets)
    seen, uniq = set(), []
    for t in tweets:
        if t["id"] not in seen:
            seen.add(t["id"]); uniq.append(t)
    uniq.sort(key=lambda t: t["created_at"])
    save_json(out, {"handle": info["userName"], "fetched_at": now_iso(), "min_faves": mf, "deep_done": True,
                    "info": {k: info.get(k) for k in ("userName", "name", "followers", "description", "profilePicture",
                                                      "createdAt", "statusesCount", "isBlueVerified", "location")},
                    "tweets": uniq})
    span = f"{uniq[0]['created_at'][:10]}..{uniq[-1]['created_at'][:10]}" if uniq else "-"
    print(f"{handle}: followers={followers} mf={mf} tweets={len(uniq)} {span} credits_so_far={api.credits_used}",
          flush=True)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    if not args:
        args = [a["handle"] for a in load_json(DATA / "accounts.json", [])]
    api = TwitterAPI(credit_limit=520_000)
    from concurrent.futures import ThreadPoolExecutor

    def one(h):
        try:
            if "--deepen" in sys.argv:
                deepen(api, h)
            else:
                fetch(api, h, force)
        except Exception as e:
            print(f"!! {h}: {e}", flush=True)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, args))
    print("TOTAL credits used:", api.credits_used)


if __name__ == "__main__":
    main()
