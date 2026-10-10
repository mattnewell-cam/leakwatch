"""Resolve leak claims: did they come true, when did the info become public, and was the leaker early?"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from .common import DATA, MODEL_SMART, load_json
from .llm import S, arr, call_json, enum, obj

VERDICTS = ["true", "mostly_true", "partly_true", "false", "pending", "already_public", "unverifiable"]

RES_SCHEMA = obj({
    "id": S,
    "verdict": enum(*VERDICTS),
    "public_date": {"type": ["string", "null"]},
    "official_date": {"type": ["string", "null"]},
    "explanation": S,
    "evidence": arr(obj({"title": S, "url": S})),
    "confidence": enum("low", "medium", "high"),
})
SCHEMA = obj({"results": arr(RES_SCHEMA)})

SYSTEM = """You are a meticulous fact-checker grading AI-industry leak claims for a public leaker-accuracy leaderboard.
Today is {today}. STEP 1 for every claim - NOVELTY: before judging truth, check whether this specific information was already public
before the tweet (official blog/changelog/announcement, news article, Hacker News/Reddit post, a TestingCatalog/other
leaker post, an exec's public statement, a model already visible on an arena/OpenRouter publicly identified). Many
accounts relay or react to public info; a relay is already_public even if the info later proved true. Look at the
tweet text for cues ("per", "reportedly", links, quote-tweets, "BREAKING", screenshots of articles).
STEP 2 - TRUTH: for each claim decide what actually happened, using the PUBLIC EVENTS timeline provided plus web
search (search whenever the timeline doesn't settle it - check official announcements and reputable reporting).

Verdicts:
- true: the core assertion happened essentially as stated (names/dates/details right; timing within the stated window,
  or within ~a few days for an exact date).
- mostly_true: core assertion right, a secondary detail wrong (e.g. right product, date off by 1-3 weeks; right model,
  wrong name).
- partly_true: some substance right but a major element wrong or it happened much later than claimed.
- false: did not happen, or the stated deadline passed without it happening, or details clearly contradicted.
- pending: deadline (resolve_by) not yet passed and not yet confirmed or contradicted.
- already_public: the information was ALREADY public (officially announced or widely reported) before the tweet - no
  credit for leaking it. Check this carefully against the timeline and reporting dates.
- unverifiable: cannot be confirmed or refuted from public info even in principle (internal-only facts never reported).

public_date: the YYYY-MM-DD on which the claimed info FIRST became public - officially confirmed OR reported by a
major outlet / widely circulated - whichever came first (null if never). Used to compute how far ahead of public
knowledge the leaker was, so be precise.
official_date: YYYY-MM-DD the company/government officially confirmed or shipped it (null if never).
JOURNALISTS: if account_type is journalist and the tweet promotes their own outlet's report, that report IS the scoop:
do NOT mark it already_public just because their article appeared that day - judge whether the reporting proved true
(public_date = their report date, official_date = official confirmation). Only mark already_public if someone else
had already reported it earlier.
NO CIRCULAR EVIDENCE: a report is never confirmation of itself. A journalist's article, or a leaker's own tweet, or
articles merely repeating that report, do NOT make a claim true. "true"/"mostly_true" require INDEPENDENT confirmation:
official announcement/confirmation, the event verifiably happening (deal closed, model shipped, person left), or a
different outlet confirming with its own sources. "In talks"/"considering"/"planning" claims: true only if the
talks/plan were later confirmed or the outcome happened; false if it verifiably fell through or the opposite happened;
otherwise unverifiable. Internal-state claims (memos, revenue figures, internal tensions) with no independent
confirmation are unverifiable.
explanation: 1-2 crisp sentences: what happened vs what was claimed, with dates.
evidence: 1-3 sources (official post or reputable article) - real URLs you actually found, no fabrication.
confidence: your confidence in the verdict.
Timing rules: tweet times are UTC but most leakers are US-based - interpret "today/tomorrow/Tuesday" in US Pacific
time. "Next week" means the whole following calendar week; "soon"/"imminent" means within ~3 weeks. If resolve_by
looks earlier than the claim's own stated window, use the claim's wording. For release-timing claims, missing by a
few days (<=7) is mostly_true, by 1-6 weeks is partly_true, and only later/never is false. Judge the tweet text itself
when the CLAIM restatement seems to misread it.
Be fair but strict: vague claims that could be read as right after the fact should not get "true" unless the specific
substance matches. Return one result per claim id."""


def _events_for(claims):
    ev = load_json(DATA / "events.json", [])
    labs = {c["lab"] for c in claims}
    lo = min(c["date"][:10] for c in claims)
    lo = (date.fromisoformat(lo) - timedelta(days=60)).isoformat()
    rel = [e for e in ev if e["date"] >= lo and (e["lab"] in labs or "Other" in labs or len(labs) > 2)]
    return "\n".join(f"{e['date']} [{e['lab']}] {e['title']}" for e in rel[:220]) or "(none)"


_CATS = None


def _category(handle):
    global _CATS
    if _CATS is None:
        _CATS = {a["handle"].lower(): a.get("category") for a in load_json(DATA / "accounts.json", [])}
    return _CATS.get(handle.lower(), "untracked")


def _fmt(c):
    tw = "\n".join(f"   tweet ({t['created_at'][:10]}): {t['text'][:500]}" for t in c.get("tweets", [])[:2])
    return (f"id={c['id']} | @{c['handle']} | claimed {c['date'][:10]} | lab={c['lab']} | resolve_by={c.get('resolve_by')}\n"
            f"   CLAIM: {c['claim']}\n{tw}")


def resolve_batch(claims, model=MODEL_SMART, today=None, reasoning=None):
    today = today or date.today().isoformat()
    user = (f"PUBLIC EVENTS (official timeline):\n{_events_for(claims)}\n\nCLAIMS TO GRADE:\n\n" +
            "\n\n".join(_fmt(c) for c in claims))
    out = call_json(model, SYSTEM.format(today=today), user, SCHEMA, name="grades", web_search=True, timeout=600,
                    reasoning=reasoning, max_tool_calls=8)
    return {r["id"]: r for r in out["results"]}


def resolve_many(claims, batch=6, workers=8, model=MODEL_SMART, today=None, log=print):
    # Group by lab so each batch shares context; keep chronological order.
    claims = sorted(claims, key=lambda c: (c["lab"], c["date"]))
    batches = [claims[i:i + batch] for i in range(0, len(claims), batch)]
    results = {}

    def run(b):
        try:
            return resolve_batch(b, model, today)
        except Exception as e:
            log(f"resolve error: {e}")
            return {}
    with ThreadPoolExecutor(workers) as ex:
        for i, r in enumerate(ex.map(run, batches)):
            results.update(r)
            if i % 10 == 0:
                log(f"  resolved batches {i + 1}/{len(batches)}")
    return results
