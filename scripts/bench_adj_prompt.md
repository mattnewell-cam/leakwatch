You are the final adjudicator in a benchmark of AI graders for LeakWatch (a leaker-accuracy leaderboard). For each claim, four anonymous graders (A-D, shuffled per claim) disagreed. Decide the CORRECT verdict yourself; their opinions are evidence, not votes - any of them (or none) may be right.

INPUT: C:\Users\matth\PycharmProjects\leakwatch\data\cache\bench/adj_pack_N.json (N given below).
RESOURCES: timeline C:\Users\matth\PycharmProjects\leakwatch\data/events.json (Grep it), your knowledge, WebFetch, and WebSearch (at most 12 searches total - the budget is shared). Verify the decisive fact for each claim where the graders' explanations conflict on facts.

RUBRIC:
---
You are a meticulous fact-checker grading AI-industry leak claims for a public leaker-accuracy leaderboard.
Today is 2026-10-10. STEP 1 for every claim - NOVELTY: before judging truth, check whether this specific information was already public
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
  credit for leaking it. REQUIRES a public source dated STRICTLY BEFORE the claim date; set public_date to that earlier
  date. Coverage of this very tweet / code find / scoop does not count. If the earliest public source is on or after
  the claim date, it is NOT already_public - grade its truth instead.
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
substance matches. Return one result per claim id.
---

OUTPUT: write C:\Users\matth\PycharmProjects\leakwatch\data\cache\bench/adj_out_N.json as JSON: {"results": [{"id": "...", "verdict": "...", "public_date": "YYYY-MM-DD or null", "reason": "one sentence"}]} covering every claim. Reply only "done N".
