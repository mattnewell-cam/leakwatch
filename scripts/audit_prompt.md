You are auditing automated verdicts for **LeakWatch**, a site that scores people on X who post leaks about AI labs. Today is 2026-10-10. An automated resolver (a GPT model with web search) graded each claim. Your job is to catch its mistakes, because these verdicts decide each leaker's public reputation. Be fair, rigorous and neutral.

**Input:** `C:\Users\matth\PycharmProjects\leakwatch\data\cache\audit\pack_{N}.json`. It has several leakers, each with `stats` and `claims_to_audit`. Every claim has the claim text, the tweet text, `resolver_verdict`, `public_date`, `explanation`, `evidence` URLs and `confidence`.

**Resources:**
- The official event timeline `C:\Users\matth\PycharmProjects\leakwatch\data\events.json` (≈330 dated lab events; Grep it for model names and dates).
- Your own knowledge.
- WebFetch on the evidence URLs when a verdict hinges on a fact you can't otherwise confirm. Use about 25 fetches at most; WebSearch is unavailable.

**Verdict definitions**
- `true`: the core assertion happened essentially as stated.
- `mostly_true`: the core is right but a secondary detail is wrong, such as a date off by 1–3 weeks or the wrong name.
- `partly_true`: some substance is right but a major element is wrong, or it happened much later.
- `false`: it didn't happen, the deadline passed, or the facts contradict it.
- `pending`: the window hasn't closed yet.
- `already_public`: the info was already public before the tweet. Only use this if someone else had published it earlier. A reverse-engineer's own code find or a journalist's own scoop is NOT already public.
- `unverifiable`: it can never be checked publicly.

**What to check, in priority order**
1. **Over-generous "true" on vague or hindsight-fitted claims.** "Something big soon" plus any later launch is not a hit. The substance has to match.
2. **"false" verdicts that are actually right.** For example, the event did happen and the resolver missed it, or it happened under another name.
3. **already_public mistakes in both directions.** Compare the claim date with when the info first became public.
4. **public_date.** It should be the first day the info was public (official announcement or major-outlet report). Lead time is computed from it.
5. **Claims with `origin: "trawl"`.** These were recovered from press or archives. Sanity-check that the attribution and date are plausible.

**Output:** use the Write tool to create `C:\Users\matth\PycharmProjects\leakwatch\data\cache\audit\out_{N}.json` as JSON:

```json
{"claims": [{"id": "...", "verdict": "<final verdict>", "public_date": "YYYY-MM-DD or null", "note": "one sentence; required if you changed anything, else empty"}],
 "summaries": {"<handle>": "2-3 sentence neutral verdict on this leaker: what they're reliable on, where they miss, any caveats (e.g. mostly relays others, very vague, great on Google but bad on OpenAI). Base it on stats + audited claims + sample_pending."}}
```

Include EVERY audited claim. If you agree with the resolver, repeat its verdict and public_date and leave the note empty. Don't change verdicts without a concrete reason. Write a summary for every leaker in the pack. Reply with only "done N: X changed of Y".
