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
| Extract | An LLM keeps only assertions of **non-public** info (not commentary, not relays of published stories), with specificity, significance and whether the poster stated a deadline; a second pass re-reads each post and drops non-claims | `leakwatch/extract.py`, `scripts/prune_claims.py` |
| Resolve | GPT-6 Luna + web search grades **the post itself** (incl. any quoted post) against an official event timeline (`data/events.json`): true / mostly / partly / false / pending / already public / unverifiable / not a claim, plus first-public and official-confirmation dates (lead time). One timing rubric; untimed claims are never "false" just because time passed; no circular evidence | `leakwatch/resolve.py` |
| Audit | High-impact verdicts re-checked by Claude Opus; random samples blind re-graded by GPT-6 Astra (≈69% outcome agreement — the ambiguity ceiling between strong graders). Corrections marked in `resolution.vetted` | `scripts/apply_audit.py`, `scripts/astra_audit.py` |
| Score | Credibility (expected credit, Bayesian, claims about one event counted once), coverage, impact, Leak score, and no-hindsight legitimacy recalibrated on the backtest (`scripts/tune_prior.py`) | `leakwatch/scoring.py` |
| Daily | 06:17 UTC: new posts from tracked accounts (catch-up after missed runs, retry queue), a wider X search for viral leaks, extraction + prune, story linking (corroboration / repeats), grading of new claims and re-checks of open ones, weekly blurb refresh, rebuild, deploy | `leakwatch/daily.py`, `.github/workflows/daily.yml` |

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

- Models: `LEAKWATCH_MODEL_FAST` and `LEAKWATCH_MODEL_SMART` (both default `gpt-6-luna`, which beat GPT-5.4 in a 300-claim grading benchmark).
- Daily twitterapi.io spend is capped at 20k credits (about $0.20). Typical spend is about 3–6k credits per day. Daily OpenAI spend is roughly $0.50–$2, depending on how many pending claims come due.
- Re-run the workflow by hand from the Actions tab ("Daily leak update" → Run workflow).
- To add a leaker, add `{"handle": "...", "category": "anon_insider|reverse_engineer|journalist|aggregator|commentator"}` to `data/accounts.json`, then run `python -m scripts.backfill_fetch <handle>`, `python -m scripts.extract_claims <handle>`, `python -m scripts.import_backfill` and `python -m scripts.resolve_backfill`.

## Status (2026-10-11, after the overnight overhaul)

- 45 tracked accounts; 3,780 live claims (non-claims pruned), 1,487 settled, 705 pending.
- Grading reliability: a stronger model (GPT-6 Astra) blind re-graded a random sample of un-audited verdicts and agreed on the outcome category 69% of the time; disagreements run both ways. Aggregate scores are far more robust than any single verdict.
- Top leakers by Leak score: @btibor91, @AiBattle_, @testingcatalog, @legit_api.
- See `NOTES.md` for the full log of what changed and why.
- twitterapi.io: ~400k credits left; a daily run uses ~3–6k (≈ 2–3 months). Top up at twitterapi.io/dashboard.

## Caveats

Automated grading is imperfect, so every claim links to its sources. Deleted tweets are only captured when someone documented them. Journalists are graded on what they post on X.
