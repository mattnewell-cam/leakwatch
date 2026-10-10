"""Daily run: pull new posts, extract + score new leak claims, re-check pending claims, refresh profiles.

Usage: python -m leakwatch.daily [--no-resolve] [--hours 48]
"""
import calendar
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .common import DATA, MODEL_FAST, MODEL_SMART, load_json, now_iso, save_json
from .extract import extract_batch, scope_filter
from .llm import USAGE, S, arr, call_json, obj
from .resolve import resolve_many
from .twitter import Budget, TwitterAPI

DAILY_CREDIT_CAP = 20_000          # ~ $0.20/day of twitterapi.io credit
MAX_RESOLVE_PER_DAY = 160
VIRAL_MIN_LIKES = 400              # untracked accounts only surface if a claim goes viral
NEWCOMER_MIN_FOLLOWERS = 2000
NEWCOMER_MIN_ACCOUNT_AGE_DAYS = 120
LABS_Q = ("(openai OR anthropic OR gemini OR deepmind OR gpt OR claude OR grok OR xai OR deepseek OR llama OR "
          "mistral OR qwen OR kimi OR opus OR sonnet OR codex)")
SEARCHES = [
    f'(leak OR leaked OR leaks OR scoop OR "hearing that" OR "i\'m hearing" OR "im hearing" OR "my sources" OR '
    f'"sources say" OR "i\'m told" OR insiders OR codename) {LABS_Q} -filter:replies',
    f'("coming next week" OR "launching next week" OR "release date" OR "spotted" OR "found in the code" OR '
    f'"in the app code" OR "a/b test" OR "being tested" OR "mystery model" OR "stealth model") {LABS_Q} -filter:replies',
]


def log(*a):
    print(*a, flush=True)


def ts(dt):
    return calendar.timegm(dt.timetuple())


def mf_for(followers):
    return int(min(300, max(10, (followers or 0) / 1000)))


def fetch_tracked(api, accounts, since):
    """One OR-query per group of accounts with similar like thresholds."""
    groups = defaultdict(list)
    for a in accounts:
        mf = mf_for((a.get("profile") or {}).get("followers"))
        bucket = 10 if mf <= 15 else 25 if mf <= 35 else 50 if mf <= 70 else 100 if mf <= 150 else 200
        groups[bucket].append(a["handle"])
    tweets = []
    for mf, hs in groups.items():
        for i in range(0, len(hs), 8):
            q = "(" + " OR ".join(f"from:{h}" for h in hs[i:i + 8]) + f") min_faves:{mf} since_time:{ts(since)}"
            tweets += list(api.search(q, "Latest", max_tweets=300))
    return tweets


def search_general(api, since):
    out = []
    for q in SEARCHES:
        out += list(api.search(f"{q} min_faves:{VIRAL_MIN_LIKES} since_time:{ts(since)}", "Top", max_tweets=80))
    return out


def newcomer_ok(t):
    a = t["author"]
    if (a.get("followers") or 0) < NEWCOMER_MIN_FOLLOWERS or t["likes"] < VIRAL_MIN_LIKES:
        return False
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))).days
    except Exception:
        return False
    return age >= NEWCOMER_MIN_ACCOUNT_AGE_DAYS


STORY_SCHEMA = obj({"matches": arr(obj({"new_id": S, "same_as": arr(S)}))})
STORY_SYS = """Match new leak claims to earlier claims that assert substantially the SAME thing (same product/event, compatible
details). Different but related claims are NOT matches. Return for each new claim the ids of matching earlier claims
(possibly empty)."""


def link_stories(new, claims):
    """Assign story_id so corroborating claims from different leakers are linked."""
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    recent = [c for c in claims if c["date"][:10] >= cutoff]
    by_lab = defaultdict(list)
    for c in recent:
        by_lab[c["lab"]].append(c)
    byid = {c["id"]: c for c in claims}
    for lab, ns in defaultdict(list, {k: [n for n in new if n["lab"] == k] for k in {n["lab"] for n in new}}).items():
        pool = [c for c in by_lab.get(lab, []) if c["id"] not in {n["id"] for n in ns}][-120:]
        if not pool:
            continue
        txt = ("EARLIER CLAIMS:\n" + "\n".join(f"{c['id']} (@{c['handle']}, {c['date'][:10]}): {c['claim']}" for c in pool) +
               "\n\nNEW CLAIMS:\n" + "\n".join(f"{c['id']} (@{c['handle']}, {c['date'][:10]}): {c['claim']}" for c in ns))
        try:
            res = call_json(MODEL_FAST, STORY_SYS, txt, STORY_SCHEMA, name="stories")["matches"]
        except Exception as e:
            log("story link error", e)
            continue
        for m in res:
            n = byid.get(m["new_id"])
            same = [byid[i] for i in m["same_as"] if i in byid]
            if not n or not same:
                continue
            root = min(same + [n], key=lambda c: c["date"])
            sid = root.get("story_id") or root["id"]
            for c in same + [n]:
                c["story_id"] = sid


def main():
    hours = 48
    if "--hours" in sys.argv:
        hours = int(sys.argv[sys.argv.index("--hours") + 1])
    accounts = [a for a in load_json(DATA / "accounts.json") if not a.get("skip")]
    tracked = {a["handle"].lower(): a for a in accounts}
    claims = load_json(DATA / "claims.json", [])
    state = load_json(DATA / "state.json", {})
    seen = set(state.get("seen_tweets", [])[-20000:])
    for c in claims:
        for t in c.get("tweets", []):
            seen.add(t["id"])
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    api = TwitterAPI(credit_limit=DAILY_CREDIT_CAP)

    # 1. pull posts
    tweets = []
    try:
        tweets += fetch_tracked(api, accounts, since)
        log(f"tracked tweets: {len(tweets)} (credits {api.credits_used})")
        gen = search_general(api, since)
        log(f"general search tweets: {len(gen)} (credits {api.credits_used})")
        tweets += [t for t in gen if t["author"]["handle"] and
                   (t["author"]["handle"].lower() in tracked or newcomer_ok(t))]
    except Budget as e:
        log("twitter budget hit:", e)
    uniq = {}
    for t in tweets:
        if t["id"] not in seen and t["author"]["handle"]:
            uniq[t["id"]] = t
    log(f"new unseen tweets: {len(uniq)}")

    # 2. extract claims per author
    by_author = defaultdict(list)
    for t in uniq.values():
        by_author[t["author"]["handle"]].append(t)
    new_claims = []
    newcomers = load_json(DATA / "newcomers.json", {})
    for handle, tw in by_author.items():
        acct = tracked.get(handle.lower())
        cat = acct["category"] if acct else "untracked account (no track record)"
        tw.sort(key=lambda t: t["created_at"])
        for i in range(0, len(tw), 30):
            try:
                cs = extract_batch(handle, cat, tw[i:i + 30], model=MODEL_SMART)
            except Exception as e:
                log("extract error", handle, e)
                continue
            byid = {t["id"]: t for t in tw}
            for c in cs:
                if not acct and c["significance"] < 3:
                    continue
                ts_ = [byid[x] for x in c["tweet_ids"] if x in byid]
                cid = f"{handle.lower()}-{c['tweet_ids'][0]}"
                if any(x["id"] == cid for x in claims) or any(x["id"] == cid for x in new_claims):
                    continue
                new_claims.append({
                    "id": cid, "handle": handle, "date": min(t["created_at"] for t in ts_), "claim": c["claim"],
                    "lab": c["lab"], "topic": c["topic"], "specificity": c["specificity"],
                    "significance": c["significance"], "resolve_by": c["resolve_by"], "hedged": c["hedged"],
                    "source_type": c["source_type"], "cryptic": c["cryptic"],
                    "tweets": [{"id": t["id"], "url": t["url"], "created_at": t["created_at"], "text": t["text"][:1200],
                                "likes": t["likes"]} for t in ts_],
                    "origin": "daily", "first_seen": now_iso(), "feed_date": now_iso()})
                if not acct:
                    a = ts_[0]["author"]
                    newcomers[handle.lower()] = {"handle": handle, "name": a.get("name"), "avatar": a.get("avatar"),
                                                 "followers": a.get("followers"), "bio": a.get("description"),
                                                 "first_seen": newcomers.get(handle.lower(), {}).get("first_seen") or now_iso()}
    if new_claims:
        new_claims = scope_filter(new_claims)
    log(f"new claims: {len(new_claims)}")
    if new_claims:
        link_stories(new_claims, claims + new_claims)
    claims += new_claims

    # 3. re-check pending claims (overdue first, then oldest-checked)
    if "--no-resolve" not in sys.argv:
        today = date.today().isoformat()
        def due(c):
            r = c.get("resolution") or {}
            if c.get("specificity", 3) < 2:
                return False
            if not r:
                return True
            if r.get("verdict") != "pending":
                return False
            last = (r.get("resolved_at") or "2000-01-01")[:10]
            overdue = (c.get("resolve_by") or "9999") <= today
            stale_check = (date.fromisoformat(today) - date.fromisoformat(last)).days >= (2 if overdue else 7)
            return stale_check
        todo = [c for c in claims if due(c)]
        todo.sort(key=lambda c: (0 if (c.get("resolve_by") or "9999") <= today else 1,
                                 ((c.get("resolution") or {}).get("resolved_at") or "")))
        todo = todo[:MAX_RESOLVE_PER_DAY]
        log(f"resolving {len(todo)} claims")
        res = resolve_many(todo, batch=8, workers=8, model=MODEL_SMART, today=today, log=log)
        byid = {c["id"]: c for c in claims}
        for k, v in res.items():
            c = byid.get(k)
            if not c:
                continue
            prev = (c.get("resolution") or {}).get("verdict")
            v.pop("id", None)
            v["resolved_at"] = now_iso()
            if c.get("resolution", {}).get("vetted"):
                v["vetted"] = c["resolution"]["vetted"]
            c["resolution"] = v
            if prev == "pending" and v["verdict"] not in ("pending",):
                c["feed_date"] = now_iso()       # newly resolved -> resurfaces in the feed
                c["resolved_recently"] = True

    # 4. weekly profile refresh (followers / avatars)
    if now.weekday() == 0:
        for a in accounts:
            try:
                info = api.user_info(a["handle"])
                if info.get("userName"):
                    a["profile"] = {"name": info.get("name"), "avatar": info.get("profilePicture"),
                                    "followers": info.get("followers"), "bio": info.get("description")}
            except Exception:
                pass
        save_json(DATA / "accounts.json", accounts)

    claims.sort(key=lambda c: c["date"])
    save_json(DATA / "claims.json", claims)
    save_json(DATA / "newcomers.json", newcomers)
    state["seen_tweets"] = list(seen | set(uniq))[-20000:]
    state["last_run"] = now_iso()
    state.setdefault("runs", []).append({"at": now_iso(), "new_claims": len(new_claims), "tweets": len(uniq),
                                         "twitter_credits": api.credits_used, "openai": dict(USAGE)})
    state["runs"] = state["runs"][-60:]
    save_json(DATA / "state.json", state)
    log(f"done. twitter credits {api.credits_used}; openai {USAGE}")


if __name__ == "__main__":
    main()
