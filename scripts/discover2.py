import collections, json, re, calendar
from datetime import datetime
from leakwatch.common import DATA, save_json, load_json
from leakwatch.twitter import TwitterAPI
api = TwitterAPI(credit_limit=30_000)
LABS = "(openai OR anthropic OR gemini OR gpt OR claude OR grok OR deepseek OR deepmind OR xai OR llama OR opus)"
Q = [f'("scoop" OR "my source" OR "my sources" OR "a source" OR "i\'m told" OR "ive been told" OR "i\'ve been told" OR "hearing" OR "codename" OR "insiders") {LABS} min_faves:200',
     f'("called it" OR "was right" OR "leaker" OR "leakers" OR "leaked by") {LABS} min_faves:80']
def ts(y,m,d): return calendar.timegm(datetime(y,m,d).timetuple())
W=[(ts(2023,1,1),ts(2024,1,1)),(ts(2024,1,1),ts(2024,9,1)),(ts(2024,9,1),ts(2025,3,1)),(ts(2025,3,1),ts(2025,9,1)),(ts(2025,9,1),ts(2026,3,1)),(ts(2026,3,1),ts(2026,7,1)),(ts(2026,7,1),ts(2026,10,11))]
tw=[]
for q in Q:
    for a,b in W:
        tw += list(api.search(f"{q} since_time:{a} until_time:{b}","Top",max_tweets=60))
save_json(DATA/"cache"/"discover2_tweets.json", tw)
c=collections.Counter(t["author"]["handle"] for t in tw[:len(tw)//2+200])
print("AUTHORS (scoop-language):"); print([(h,n) for h,n in collections.Counter(t["author"]["handle"] for t in tw if re.search(r"scoop|source|told|hearing|codename|insider",t["text"],re.I)).most_common(60)])
m=collections.Counter()
for t in tw:
    if re.search(r"called it|was right|leaker|leaked by",t["text"],re.I):
        for x in re.findall(r"@(\w{3,15})",t["text"]): m[x]+=1
print("MENTIONED w/ leaker/called-it:", m.most_common(50))
print("credits",api.credits_used)
