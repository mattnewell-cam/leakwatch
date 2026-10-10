"""Find accounts that repeatedly post high-engagement leak-style claims about AI labs."""
import collections, json, sys, calendar
from datetime import datetime
from leakwatch.common import DATA, save_json
from leakwatch.twitter import TwitterAPI

api = TwitterAPI(credit_limit=90_000)
LABS = "(openai OR anthropic OR gemini OR gpt OR claude OR grok OR deepseek OR deepmind OR xai OR llama OR sora OR o3 OR opus)"
QUERIES = [
    f'(leak OR leaked OR leaks OR "hearing that" OR "i\'m hearing" OR "im hearing" OR "sources say" OR "my sources" OR insider OR "internally") {LABS}',
    f'("coming next week" OR "dropping" OR "launching" OR "release date" OR "is coming" OR "imminent" OR "codename") {LABS}',
    f'("reliable leaker" OR "known leaker" OR "leaker" OR "according to @") {LABS}',
]
def ts(y, m, d): return calendar.timegm(datetime(y, m, d).timetuple())
WINDOWS = [(ts(2023,1,1), ts(2023,9,1)), (ts(2023,9,1), ts(2024,4,1)), (ts(2024,4,1), ts(2024,10,1)), (ts(2024,10,1), ts(2025,4,1)),
           (ts(2025,4,1), ts(2025,10,1)), (ts(2025,10,1), ts(2026,4,1)), (ts(2026,4,1), ts(2026,10,11))]
tweets = []
for q in QUERIES:
    for a, b in WINDOWS:
        qq = f"{q} min_faves:300 since_time:{a} until_time:{b}"
        try:
            got = list(api.search(qq, "Top", max_tweets=60))
        except Exception as e:
            print("ERR", e); continue
        tweets += got
        print(len(got), datetime.utcfromtimestamp(a).date(), q[:40], api.credits_used, flush=True)
save_json(DATA / "cache" / "discover_tweets.json", tweets)
c = collections.Counter(t["author"]["handle"] for t in tweets)
likes = collections.defaultdict(int)
for t in tweets: likes[t["author"]["handle"]] += t["likes"]
mentions = collections.Counter()
import re
for t in tweets:
    for m in re.findall(r"@(\w{3,15})", t["text"]): mentions[m] += 1
print("\nTOP AUTHORS:")
for h, n in c.most_common(80): print(n, h, likes[h])
print("\nTOP MENTIONED:")
for h, n in mentions.most_common(60): print(n, h)
print("credits", api.credits_used)
