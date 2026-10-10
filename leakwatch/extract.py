"""Turn raw tweets into structured leak claims (LLM pass)."""
import json
from concurrent.futures import ThreadPoolExecutor

from .common import MODEL_FAST, MODEL_SMART
from concurrent.futures import ThreadPoolExecutor as _TPE

from .llm import B, I, S, arr, call_json, enum, obj

LABS = ["OpenAI", "Anthropic", "Google", "xAI", "Meta", "Microsoft", "Apple", "Amazon", "Nvidia", "DeepSeek",
        "Alibaba", "Mistral", "Moonshot", "Zhipu", "SSI", "Thinking Machines", "Other"]
TOPICS = ["model_release", "model_capability", "product_feature", "corporate", "people", "deal_funding", "policy_legal",
          "other"]

CLAIM_SCHEMA = obj({
    "tweet_ids": arr(S),
    "claim": S,
    "lab": enum(*LABS),
    "topic": enum(*TOPICS),
    "specificity": I,
    "significance": I,
    "resolve_by": {"type": ["string", "null"]},
    "hedged": B,
    "source_type": enum("insider", "code_or_testing_evidence", "journalism", "relayed", "speculation"),
    "cryptic": B,
})
SCHEMA = obj({"claims": arr(CLAIM_SCHEMA)})

SYSTEM = """You extract LEAK CLAIMS from tweets for a site that scores the track record of AI-industry leakers.

A leak claim = an assertion of NON-PUBLIC information (at the time of the tweet) about frontier AI labs or the AI industry
that can in principle turn out true or false. Examples: an unreleased model's name/codename, release timing, capabilities
or benchmark numbers of unreleased models, features found in app code or A/B tests, internal events at a lab, upcoming
funding/valuation/IPO/deal/acquisition, exec hires or departures, government actions toward labs - BEFORE they are announced.
Also count cryptic teasers that clearly imply insider knowledge of a specific upcoming event (mark cryptic=true).

NOT claims: commentary/opinions on already-announced news, reactions to releases, benchmarks of public models,
memes, jokes, general predictions about AI progress with no insider angle ("AGI by 2030"), tutorials, self-promotion,
quoting official announcements.
CRUCIAL - the info must be NON-PUBLIC when tweeted:
- If it matches an official event already announced on/before the tweet date (see the PUBLIC EVENTS list provided, and
  your own knowledge), it is NOT a claim.
- If the tweet relays a published media report ("per The Information", "Bloomberg reports", a linked article, "according
  to X user @..."), it is NOT the author's claim - UNLESS the author is the journalist who broke it (account type
  journalist and it's their own outlet's scoop) -> then source_type="journalism".
- Commentary on something that just launched, rumours everyone already knows (e.g. "GPT-5 is coming" after OpenAI said
  so), or restating an earlier leak by someone else are NOT claims.
- "relayed" is only for unattributed hearsay the author vouches for ("I'm hearing from a friend at X...").

For each claim:
- tweet_ids: tweet id(s) making it (merge a thread / repeated tweets of the same claim into one claim).
- claim: one standalone sentence restating precisely what was asserted, including the lab, product, and any timing
  in ABSOLUTE terms (convert "next week" etc. using the tweet date). Don't add info not in the tweet. Keep the leaker's
  hedges ("reportedly", "possibly") if present.
- specificity 1-5: 1 = vague vibes ("something big soon"); 2 = names a thing loosely; 3 = names product/event + rough
  timing; 4 = precise detail (codename, specific feature, week); 5 = exact date / number / multiple checkable details.
- significance 1-5: 1 = trivial UI tweak; 2 = minor feature; 3 = notable product/model update; 4 = major model release or
  big corporate event; 5 = frontier flagship release or industry-shaking event (CEO fired, $100B deal, GPT-5 launch date).
- resolve_by: YYYY-MM-DD by which the claim should have come true if it is right (use stated/implied timing; if
  none, use tweet date + 180 days), or null if inherently unfalsifiable.
- hedged: true if heavily caveated ("rumor", "unconfirmed", "might").
- source_type: insider (claims sources/inside knowledge), code_or_testing_evidence (found in code, A/B test, model
  arena, API listing), journalism (reporter's own reporting/article), relayed (passing on someone else's leak),
  speculation (pure guess presented as likely).
- cryptic: true for teasing/riddle style.
Return {"claims": []} if no tweets qualify. Be strict - most tweets are not claims."""


def _fmt(t):
    s = f"[id={t['id']}] {t['created_at'][:16]} likes={t['likes']}\n{t['text']}"
    if t.get("quoted"):
        s += f"\n  (quoting @{t['quoted']['handle']}: {t['quoted']['text'][:400]})"
    if t.get("reply_to"):
        s = f"(reply to @{t['reply_to']}) " + s
    return s


def extract_batch(handle, category, tweets, model=MODEL_FAST):
    user = (f"Author: @{handle} (account type: {category})\n\nTweets:\n\n" +
            "\n\n---\n\n".join(_fmt(t) for t in tweets))
    out = call_json(model, SYSTEM, user, SCHEMA, name="claims")
    ids = {t["id"] for t in tweets}
    claims = []
    for c in out["claims"]:
        c["tweet_ids"] = [i for i in c["tweet_ids"] if i in ids]
        if c["tweet_ids"]:
            c["specificity"] = max(1, min(5, c["specificity"]))
            c["significance"] = max(1, min(5, c["significance"]))
            claims.append(c)
    return claims


def extract_all(handle, category, tweets, batch=30, workers=6, model=MODEL_SMART):
    batches = [tweets[i:i + batch] for i in range(0, len(tweets), batch)]
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(lambda b: _safe(handle, category, b, model), batches))
    return [c for r in results for c in r]


def _safe(handle, category, b, model):
    try:
        return extract_batch(handle, category, b, model)
    except Exception as e:
        print(f"  extract error @{handle}: {e}", flush=True)
        return []


SCOPE_SCHEMA = obj({"in_scope_ids": arr(S)})
SCOPE_SYS = """Keep only claims about AI: AI models, AI products/features, AI labs & their people/finances/deals/legal
issues, AI chips/compute/data centers, government AI policy. Drop claims about unrelated topics (e.g. iPhone hardware,
general tech, crypto, Tesla cars, politics unrelated to AI). Return the ids to keep."""


def scope_filter(claims):
    out = set()

    def run(b):
        txt = "\n".join(f"{c['id']}: [{c['lab']}] {c['claim']}" for c in b)
        try:
            return call_json(MODEL_FAST, SCOPE_SYS, txt, SCOPE_SCHEMA, name="scope")["in_scope_ids"]
        except Exception as e:
            print("scope err", e)
            return [c["id"] for c in b]
    batches = [claims[i:i + 60] for i in range(0, len(claims), 60)]
    with _TPE(8) as ex:
        for r in ex.map(run, batches):
            out.update(r)
    return [c for c in claims if c["id"] in out]


