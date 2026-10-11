"""Daily run: pull new posts, extract + score new leak claims, re-check open claims, refresh profiles.

Usage: python -m leakwatch.daily [--no-resolve] [--hours 48]
"""
import calendar
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .common import DATA, MODEL_FAST, MODEL_SMART, load_json, now_iso, save_json
from .extract import extract_batch, scope_filter
from .llm import USAGE, S, arr, call_json, obj
from .resolve import deadline_stated, resolve_many
from .scoring import effective_verdict
from .twitter import Budget, TwitterAPI

DAILY_CREDIT_CAP = 20_000          # ~ $0.20/day of twitterapi.io credit
MAX_RESOLVE_PER_DAY = 120
MAX_LOOKBACK_HOURS = 24 * 7        # catch up after outages, but never more than a week
EXTRACT_TIME_BUDGET = 35 * 60      # seconds; leaves room in the 90-min job for resolution + build
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


def fetch_tracked(api, accounts, since, out):
    """One OR-query per group of accounts with similar like thresholds. Appends to `out` as pages arrive, so tweets
    already paid for survive a budget stop."""
    groups = defaultdict(list)
    for a in accounts:
        mf = mf_for((a.get("profile") or {}).get("followers"))
        bucket = 10 if mf <= 15 else 25 if mf <= 35 else 50 if mf <= 70 else 100 if mf <= 150 else 200
        groups[bucket].append(a["handle"])
    for mf, hs in groups.items():
        for i in range(0, len(hs), 8):
            q = "(" + " OR ".join(f"from:{h}" for h in hs[i:i + 8]) + f") min_faves:{mf} since_time:{ts(since)}"
            for t in api.search(q, "Latest", max_tweets=300):
                out.append(t)


def search_general(api, since, out):
    for q in SEARCHES:
        for t in api.search(f"{q} min_faves:{VIRAL_MIN_LIKES} since_time:{ts(since)}", "Top", max_tweets=80):
            out.append(t)


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
STORY_SYS = """Match each NEW leak claim to OTHER claims (earlier ones, or other new ones) that assert substantially the
SAME thing (same product/event, compatible details, not contradictory - "will release X" vs "won't release X" is NOT a
match). Related-but-different claims are NOT matches. Return for each new claim the ids of matching claims (possibly
empty). Only use ids from the lists given."""


def link_stories(new, claims):
    """Link claims about the same thing. Same author repeating themselves -> repeat_of (scored once);
    different authors -> shared story_id (corroboration)."""
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    live = [c for c in claims if not c.get("pruned")]
    byid = {c["id"]: c for c in live}
    new_ids = {n["id"] for n in new}
    for lab in {n["lab"] for n in new}:
        ns = [n for n in new if n["lab"] == lab]
        pool = [c for c in live if c["lab"] == lab and c["date"][:10] >= cutoff and c["id"] not in new_ids][-120:]
        allowed = {c["id"] for c in pool} | {n["id"] for n in ns}
        txt = ("EARLIER CLAIMS:\n" + ("\n".join(f"{c['id']} (@{c['handle']}, {c['date'][:10]}): {c['claim']}"
                                               for c in pool) or "(none)") +
               "\n\nNEW CLAIMS:\n" + "\n".join(f"{c['id']} (@{c['handle']}, {c['date'][:10]}): {c['claim']}" for c in ns))
        try:
            res = call_json(MODEL_FAST, STORY_SYS, txt, STORY_SCHEMA, name="stories")["matches"]
        except Exception as e:
            log("story link error", e)
            continue
        for m in res:
            n = byid.get(m["new_id"]) if m["new_id"] in {x["id"] for x in ns} else None
            same = [byid[i] for i in m["same_as"] if i in allowed and i in byid and i != m["new_id"]]
            if not n or not same:
                continue
            mine = [c for c in same if c["handle"].lower() == n["handle"].lower() and c["date"] < n["date"]]
            if mine:
                n["repeat_of"] = min(mine, key=lambda c: c["date"])["id"]
            others = [c for c in same if c["handle"].lower() != n["handle"].lower()]
            if others:
                group = others + [n]
                # merge whole existing groups, not just the matched members
                sids = {c.get("story_id") for c in group if c.get("story_id")}
                members = [c for c in live if c.get("story_id") in sids] + group
                root = min(members, key=lambda c: c["date"])
                sid = root.get("story_id") or root["id"]
                for c in members:
                    c["story_id"] = sid


def due_for_check(c, today):
    """Which claims to (re)grade today."""
    if c.get("pruned") or c.get("specificity", 3) < 2 or c.get("repeat_of"):
        return False
    r = c.get("resolution") or {}
    if not r or c.get("_needs_regrade"):
        return True
    last = (r.get("resolved_at") or "2000-01-01")[:10]
    age_since_check = (date.fromisoformat(today) - date.fromisoformat(last)).days
    v = effective_verdict(c)
    if v == "pending":
        overdue = deadline_stated(c) and c["resolve_by"][:10] <= today
        if overdue:
            return age_since_check >= 3
        # "can't be confirmed yet" internal-state claims change slowly -> monthly; genuinely open ones fortnightly
        return age_since_check >= (30 if r.get("verdict") == "unverifiable" else 14)
    if v == "false" and deadline_stated(c):
        # a release can still land within the lateness grace window -> keep checking for 6 weeks after the deadline
        grace_end = (date.fromisoformat(c["resolve_by"][:10]) + timedelta(days=45)).isoformat()
        if today <= grace_end:
            return age_since_check >= 7
        return last < grace_end                    # one final look after the window closes
    if v == "unverifiable":
        # internal claims sometimes get confirmed later; re-look occasionally during the first year
        young = c["date"][:10] >= (date.fromisoformat(today) - timedelta(days=365)).isoformat()
        return young and age_since_check >= 60
    return False


T0 = time.time()


def main():
    hours = 48
    if "--hours" in sys.argv:
        hours = int(sys.argv[sys.argv.index("--hours") + 1])
    all_accounts = load_json(DATA / "accounts.json")
    accounts = [a for a in all_accounts if not a.get("skip")]
    tracked = {a["handle"].lower(): a for a in accounts}
    claims = load_json(DATA / "claims.json", [])
    state = load_json(DATA / "state.json", {})
    now = datetime.now(timezone.utc)
    # seen: recently processed tweet ids with timestamps (expire after the max lookback) + ids already in claims
    seen_recent = state.get("seen_recent") or {}
    expire = (now - timedelta(hours=MAX_LOOKBACK_HOURS + 24)).isoformat()
    seen_recent = {k: v for k, v in seen_recent.items() if v >= expire}
    seen = set(seen_recent) | {t["id"] for c in claims for t in c.get("tweets", [])}
    # look back far enough to cover any missed runs (with overlap), capped
    since = now - timedelta(hours=hours)
    if state.get("last_run"):
        try:
            last = datetime.fromisoformat(state["last_run"].replace("Z", "+00:00"))
            since = min(since, last - timedelta(hours=24))
        except ValueError:
            pass
    since = max(since, now - timedelta(hours=MAX_LOOKBACK_HOURS))
    api = TwitterAPI(credit_limit=DAILY_CREDIT_CAP)

    # 1. pull posts
    tracked_tw, general_tw = [], []
    for name, fn, out in (("tracked", fetch_tracked, tracked_tw), ("general search", search_general, general_tw)):
        try:
            if fn is fetch_tracked:
                fn(api, accounts, since, out)
            else:
                fn(api, since, out)
        except Budget as e:
            log("twitter budget hit:", e)
            break
        except Exception as e:                  # network/API trouble: keep what we already have, carry on
            log(f"{name} fetch error (partial results kept):", str(e)[:200])
        log(f"{name} tweets: {len(out)} (credits {api.credits_used})")
    # tweets whose extraction failed on a previous run are retried from the queue (not re-fetched)
    retry_q = state.get("retry_tweets") or {}
    tweets = list(retry_q.values()) + tracked_tw + [t for t in general_tw if t["author"]["handle"] and
                                                    (t["author"]["handle"].lower() in tracked or newcomer_ok(t))]
    uniq = {}
    for t in tweets:
        if t["id"] not in seen and t["author"]["handle"]:
            uniq[t["id"]] = t
    log(f"new unseen tweets: {len(uniq)}")

    # 2. extract claims per author
    by_author = defaultdict(list)
    for t in uniq.values():
        by_author[t["author"]["handle"]].append(t)
    new_claims, processed = [], set()
    existing_ids = {c["id"] for c in claims}
    newcomers = load_json(DATA / "newcomers.json", {})
    for handle, tw in by_author.items():
        if time.time() - T0 > EXTRACT_TIME_BUDGET:
            log("extraction time budget reached; remaining tweets queued for next run")
            break
        acct = tracked.get(handle.lower())
        cat = acct["category"] if acct else "untracked account (no track record)"
        tw.sort(key=lambda t: t["created_at"])
        for i in range(0, len(tw), 30):
            batch = tw[i:i + 30]
            try:
                cs = extract_batch(handle, cat, batch, model=MODEL_SMART)
            except Exception as e:
                log("extract error (queued for retry next run)", handle, str(e)[:200])
                continue
            processed.update(t["id"] for t in batch)     # only successfully-extracted tweets count as seen
            byid = {t["id"]: t for t in batch}
            for c in cs:
                if not acct and c["significance"] < 3:
                    continue
                ts_ = [byid[x] for x in c["tweet_ids"] if x in byid]
                if not ts_:
                    continue
                base = cid = f"{handle.lower()}-{c['tweet_ids'][0]}"
                k = 2
                while cid in existing_ids:
                    cid = f"{base}-{k}"
                    k += 1
                existing_ids.add(cid)
                new_claims.append({
                    "id": cid, "handle": handle, "date": min(t["created_at"] for t in ts_), "claim": c["claim"],
                    "lab": c["lab"], "topic": c["topic"], "specificity": c["specificity"],
                    "significance": c["significance"], "resolve_by": c["resolve_by"], "hedged": c["hedged"],
                    "source_type": c["source_type"], "cryptic": c["cryptic"],
                    "deadline_stated": bool(c.get("deadline_stated")) and bool(c["resolve_by"]),
                    "tweets": [{"id": t["id"], "url": t["url"], "created_at": t["created_at"], "text": t["text"][:4000],
                                "likes": t["likes"], "quoted": t.get("quoted")} for t in ts_],
                    "origin": "daily", "first_seen": now_iso(), "feed_date": now_iso()})
                if not acct:
                    a = ts_[0]["author"]
                    newcomers[handle.lower()] = {"handle": handle, "name": a.get("name"), "avatar": a.get("avatar"),
                                                 "followers": a.get("followers"), "bio": a.get("description"),
                                                 "first_seen": newcomers.get(handle.lower(), {}).get("first_seen") or now_iso()}
    if new_claims:
        new_claims = scope_filter(new_claims)
    if new_claims:
        # second opinion on the post itself: drop commentary / live-feature observations / relays (journalists exempt)
        from scripts.prune_claims import check
        from .resolve import _category
        to_check = [c for c in new_claims if _category(c["handle"]) != "journalist"]
        verdicts = {}
        for i in range(0, len(to_check), 20):
            verdicts.update(check(to_check[i:i + 20]))
        kept = []
        for c in new_claims:
            r = verdicts.get(c["id"])
            if r and not r["is_leak_claim"]:
                log(f"  pruned new claim @{c['handle']}: {c['claim'][:80]} ({r['kind']})")
                continue
            # (text corrections are not applied here: they could leave lab/deadline fields stale, and the resolver
            # grades the post itself anyway)
            if r:
                c["prune_checked"] = True
            kept.append(c)
        new_claims = kept
    log(f"new claims: {len(new_claims)}")
    if new_claims:
        link_stories(new_claims, claims + new_claims)
    claims += new_claims
    # checkpoint ingestion before the (slower, costlier) resolution step
    save_json(DATA / "claims.json", sorted(claims, key=lambda c: c["date"]))

    # 3. (re)grade claims that are due
    if "--no-resolve" not in sys.argv:
        today = date.today().isoformat()
        live = {c["id"] for c in claims if not c.get("pruned")
                and (c.get("resolution") or {}).get("verdict") != "not_a_claim"}
        for c in claims:
            if c.get("repeat_of") and c["repeat_of"] not in live:
                c.pop("repeat_of")             # original gone -> grade this one in its own right
        todo = [c for c in claims if due_for_check(c, today)]
        todo.sort(key=lambda c: (0 if not c.get("resolution") else 1,
                                 0 if (deadline_stated(c) and c["resolve_by"][:10] <= today) else 1,
                                 ((c.get("resolution") or {}).get("resolved_at") or "")))
        todo = todo[:MAX_RESOLVE_PER_DAY]
        log(f"resolving {len(todo)} claims")
        res = resolve_many([c for c in todo if c["significance"] >= 4], batch=8, workers=6, model=MODEL_SMART,
                           today=today, log=log)
        res.update(resolve_many([c for c in todo if c["significance"] < 4], batch=8, workers=6, model=MODEL_FAST,
                                today=today, log=log))
        byid = {c["id"]: c for c in claims}
        for k, v in res.items():
            c = byid.get(k)
            if not c:
                continue
            prev = effective_verdict(c) if c.get("resolution") else None
            v.pop("id", None)
            v["resolved_at"] = now_iso()
            c["resolution"] = v              # a fresh grade is not audited - drop any old audit badge
            c.pop("_needs_regrade", None)
            if prev == "pending" and effective_verdict(c) != "pending":
                c["feed_date"] = now_iso()   # newly resolved -> resurfaces in the feed

    # 4. weekly profile refresh (followers / avatars) - keeps skipped accounts in the file
    if now.weekday() == 0:
        try:
            for a in accounts:
                info = api.user_info(a["handle"])
                if info.get("userName"):
                    a["profile"] = {"name": info.get("name"), "avatar": info.get("profilePicture"),
                                    "followers": info.get("followers"), "bio": info.get("description")}
        except Budget as e:
            log("profile refresh stopped:", e)
        except Exception as e:
            log("profile refresh error:", e)
        save_json(DATA / "accounts.json", all_accounts)

    claims.sort(key=lambda c: c["date"])
    save_json(DATA / "claims.json", claims)
    save_json(DATA / "newcomers.json", newcomers)
    stamp = now_iso()
    for tid in processed:
        seen_recent[tid] = stamp
    # unprocessed tweets (extraction failed or ran out of time) are kept for the next run, oldest dropped after a week
    keep_after = (now - timedelta(hours=MAX_LOOKBACK_HOURS)).isoformat()
    state["retry_tweets"] = {tid: t for tid, t in uniq.items()
                             if tid not in processed and t["created_at"] >= keep_after[:19]}
    state["seen_recent"] = seen_recent
    state.pop("seen_tweets", None)
    state["last_run"] = stamp
    state.setdefault("runs", []).append({"at": stamp, "new_claims": len(new_claims), "tweets": len(uniq),
                                         "twitter_credits": api.credits_used, "openai": dict(USAGE)})
    state["runs"] = state["runs"][-60:]
    save_json(DATA / "state.json", state)
    log(f"done. twitter credits {api.credits_used}; openai {USAGE}")


if __name__ == "__main__":
    main()
