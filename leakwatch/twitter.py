"""Thin client for twitterapi.io with credit accounting.

Pricing (Oct 2026): ~15 credits per tweet returned, ~18 per profile; 100k credits = $1.
"""
import time
from datetime import datetime

import requests

from .common import TWITTER_KEY

BASE = "https://api.twitterapi.io"
CREDITS_PER_TWEET = 15
CREDITS_PER_PROFILE = 18


class Budget(Exception):
    pass


class TwitterAPI:
    def __init__(self, key=TWITTER_KEY, credit_limit=None):
        if not key:
            raise RuntimeError("TWITTERAPI_IO_KEY not set")
        self.s = requests.Session()
        self.s.headers["X-API-Key"] = key
        self.credits_used = 0
        self.credit_limit = credit_limit

    def _get(self, path, params):
        for attempt in range(6):
            r = self.s.get(BASE + path, params=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 + attempt * 3)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()

    def _charge(self, n):
        self.credits_used += n
        if self.credit_limit and self.credits_used > self.credit_limit:
            raise Budget(f"credit limit {self.credit_limit} exceeded")

    def search(self, query, query_type="Latest", max_tweets=200):
        """Advanced search, paginated. Yields normalized tweets."""
        cursor, n = "", 0
        while n < max_tweets:
            d = self._get("/twitter/tweet/advanced_search",
                          {"query": query, "queryType": query_type, "cursor": cursor})
            tweets = d.get("tweets") or []
            self._charge(max(len(tweets), 1) * CREDITS_PER_TWEET)
            for t in tweets:
                n += 1
                yield normalize(t)
            if not d.get("has_next_page") or not tweets or not d.get("next_cursor"):
                break
            cursor = d["next_cursor"]

    def user_info(self, handle):
        d = self._get("/twitter/user/info", {"userName": handle})
        self._charge(CREDITS_PER_PROFILE)
        return d.get("data") or {}

    def tweets_by_ids(self, ids):
        out = []
        for i in range(0, len(ids), 50):
            d = self._get("/twitter/tweets", {"tweet_ids": ",".join(ids[i:i + 50])})
            tw = d.get("tweets") or []
            self._charge(max(len(tw), 1) * CREDITS_PER_TWEET)
            out += [normalize(t) for t in tw]
        return out


def parse_date(s):
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y").strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return s


def normalize(t):
    a = t.get("author") or {}
    q = t.get("quoted_tweet") or None
    return {
        "id": t.get("id"),
        "url": t.get("url") or f"https://x.com/{a.get('userName')}/status/{t.get('id')}",
        "created_at": parse_date(t.get("createdAt", "")),
        "text": t.get("text", ""),
        "likes": t.get("likeCount", 0),
        "retweets": t.get("retweetCount", 0),
        "replies": t.get("replyCount", 0),
        "quotes": t.get("quoteCount", 0),
        "views": t.get("viewCount", 0),
        "is_reply": bool(t.get("isReply")),
        "reply_to": t.get("inReplyToUsername"),
        "author": {
            "handle": a.get("userName"),
            "name": a.get("name"),
            "followers": a.get("followers", 0),
            "verified": a.get("isBlueVerified", False),
            "created_at": parse_date(a.get("createdAt", "")),
            "avatar": a.get("profilePicture"),
            "description": a.get("description", ""),
        },
        "quoted": ({"handle": (q.get("author") or {}).get("userName"), "text": q.get("text", "")[:600],
                    "created_at": parse_date(q.get("createdAt", ""))} if q else None),
    }
