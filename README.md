# LeakWatch

**Who actually knows what's coming next?** LeakWatch tracks leak claims about AI labs made on X, such as unreleased models, release dates, codenames, features found in app code, funding, departures and deals. It grades each claim against what actually happened and scores every leaker on accuracy, how early they were, and how significant their calls were.

- **Feed**: every claim with a 0–100 *legitimacy* score. Click one to see the original post, why it scored what it did, what happened, and the leaker's track record and similar past claims.
- **Leaderboard**: leakers ranked by *Leak score*, which combines a Bayesian accuracy rate with the volume of significant, early, correct calls.
- **Profiles**: per-leaker history, accuracy by lab, best calls, biggest misses.

The site is fully static (`site/`) and is rebuilt every day by GitHub Actions.

## How it works

| Stage | What happens | Code |
|---|---|---|
| Backfill | Pulled ~45 accounts' high-engagement post history from twitterapi.io, plus famous deleted claims found in press and forum coverage | `scripts/backfill_fetch.py`, `scripts/trawl_gpt.py` |
| Extract | An LLM keeps only assertions of **non-public** info (not commentary, not relays of published stories), with specificity and significance ratings | `leakwatch/extract.py` |
| Resolve | Each claim is graded against an official event timeline (`data/events.json`) and web search: true / mostly / partly / false / pending / already public / unverifiable, plus the date it became public (lead time) | `leakwatch/resolve.py` |
| Audit | High-impact verdicts were re-checked by a second model (Claude), and corrections are marked in `resolution.vetted` | `scripts/apply_audit.py` |
| Score | Credibility, impact, Leak score, and no-hindsight legitimacy, with calibration shown on the Method page | `leakwatch/scoring.py` |
| Daily | 06:17 UTC: new posts from tracked accounts, a wider X search for viral leaks, extraction, story linking (corroboration), re-check of overdue pending claims, rebuild, deploy | `leakwatch/daily.py`, `.github/workflows/daily.yml` |

Untracked accounts only surface when a claim goes viral (≥400 likes, ≥2k followers, account ≥120 days old). They are scored with a sceptical prior and build a record over time.

## Running locally

```bash
pip install -r requirements.txt
# keys are read from ~/.leakwatch.env (TWITTERAPI_IO_KEY=..., OPENAI_API_KEY=...) or the environment
python -m leakwatch.daily --no-resolve   # pull + extract new claims
python -m scripts.build_site             # compute scores -> site/data
python -m http.server 8765 --directory site
```

## Config and costs

- Models: `LEAKWATCH_MODEL_FAST` (default `gpt-5.4-mini`) and `LEAKWATCH_MODEL_SMART` (default `gpt-5.4`).
- Daily twitterapi.io spend is capped at 20k credits (about $0.20). Typical spend is about 3–6k credits per day. Daily OpenAI spend is roughly $0.50–$2, depending on how many pending claims come due.
- Re-run the workflow by hand from the Actions tab ("Daily leak update" → Run workflow).
- To add a leaker, add `{"handle": "...", "category": "anon_insider|reverse_engineer|journalist|aggregator|commentator"}` to `data/accounts.json`, then run `python -m scripts.backfill_fetch <handle>`, `python -m scripts.extract_claims <handle>`, `python -m scripts.import_backfill` and `python -m scripts.resolve_backfill`.

## Caveats

Automated grading is imperfect, so every claim links to its sources. Deleted tweets are only captured when someone documented them. Journalists are graded on what they post on X.
