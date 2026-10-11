# Overnight log (2026-10-11 → 12)

Loop: find issue → fix → verify → push. OpenAI budget for the night: $100 (ledger: `python -m scripts.spend <ts>`,
start ts in `data/cache/budget_start.txt`).

## Done
- **Pipeline model → gpt-6-luna** (extraction, resolution, scope, story linking). Benchmarked first: Luna 77.6% vs
  GPT-5.4 59.5% bucket agreement with adjudicated gold on 294 claims (Haiku 5.5 74.8%, Opus 5.5 89.5%).
- **Resolver now grades the post itself**: post(s) shown first (incl. quoted post), extractor summary demoted to a
  pointer; new verdict `not_a_claim` (excluded from site + scores).
- **Bug: tweet text truncated to 500 chars for the resolver** (cause of the "doesn't mention Carbon" note) → full text;
  160 truncated stored tweets restored from raw cache.
- **Bug: resolver/prune prompts referenced `account_type` but never received it** (silent failed patch) → fixed.
  The earlier journalist re-grade therefore ran without knowing who was a journalist.
- **Bug: quote-tweets** — resolver/prune never saw the quoted post (1,163 claims); daily pipeline didn't store it → fixed.
- **Prune pass** (`scripts/prune_claims.py`): Luna re-reads every post, drops non-claims (commentary, reactions,
  relays of named sources, using public products, jokes/vibes, quoting officials) and corrects misstated summaries.
  Pre-June-2022 claims dropped as out of scope (2015 Facebook scoops etc.).
- Front end: no longer shows arbitrary default deadlines (only ones the leaker actually gave).

- **Prune details**: journalists exempted from the LLM prune (couldn't reliably tell own-outlet scoops from relays given
  career moves); for everyone else ~15% of claims dropped. Spot-checked samples look right.
- **GPT-6 Astra code review** (`scripts/astra_review.py`, output in data/cache/astra_review_*.md) — 28 findings, most
  real. Fixed:
  - untimed claims were judged `false` at an invented +180d deadline → resolver now told "no deadline stated" and
    told time passing alone never falsifies; scoring uses a 1-year review horizon (not attributed to the poster).
  - code finds / journalist scoops were exempt from novelty checks entirely → now already_public if someone *else*
    published first; only same-day coverage of the find itself is exempt.
  - conflicting timing rubric → one policy (exact date / window / "soon" / no deadline; state-of-affairs vs outcome).
  - false verdicts never revisited → re-checked weekly for 45 days after a stated deadline; unverifiable every 60
    days in the first year.
  - daily: ID collisions dropped extra claims from one tweet; failed extraction marked tweets as seen; Monday profile
    refresh wiped `skip` accounts; Budget stop discarded already-paid tweets; model-returned IDs could overwrite claims
    outside the batch; seen-cache kept an arbitrary set; no catch-up after missed runs; fresh grades kept old "audited"
    badges; repeats of one's own claim counted as extra hits (now `repeat_of`, scored once); same-run corroboration
    not linked; story merges split groups.
  - permanent API errors (bad key/model/schema) retried 12× → now fail fast; overall per-call deadline.
  - corroboration counted claims not people → distinct tracked accounts.
  - lead time shown against the wrong date → exported reference date + kind (public vs official).
  - drawer "past claims" showed claims made *after* the one being viewed; calibration copy mismatched the metric;
    profile silently capped at 300; unvalidated URL schemes → all fixed.
  - apply_audit could overwrite newer grades on re-run → skips claims re-graded after the audit file.
- **Full re-grade** of ~3,050 unaudited live claims with the new resolver (Luna). Benchmark note: against the old
  adjudicated gold the new resolver *looks* worse (69% vs 75%), but reading the regressions the new one is usually right
  — the old gold was made by graders who never saw quoted posts, so it misses relays (biggest shift: true→already_public).

- **Second Astra review (scoring design)** → implemented:
  - claims settled by the same event (same lab + confirmation date) count as ONE piece of evidence (five details of
    one launch ≠ five hits); impact takes the best member per event.
  - coverage shown (share of checkable claims actually settled) on leaderboard ("Settled") + profiles.
  - newcomers now learn from their own record (sceptical prior) instead of being stuck at 35%.
  - per-lab accuracy shrinks continuously toward the account's overall accuracy (no hard 3-claim threshold).
  - corroboration: only corroborators with above-average records add anything; relays get none.
  - calibration chart compares to mean score per band (not band midpoint); labelled as reconstructed backtest.
- **Prior strength + recalibration fitted on the backtest** (`scripts/tune_prior.py`): prior worth 8 claims; final
  linear recalibration q = 0.229 + 0.683·p (held-out Brier 0.122 → 0.113). Raw scores spread far too wide (claims
  scored <30 still earned ~40% credit).
- **Original finds need real confirmation**: a code/arena find or journalist scoop whose only "confirmation" is
  same-day coverage of the find itself (e.g. others seeing the same public LM Arena listing) and no later official
  confirmation → unverifiable (no credit). Fixed AiBattle/TestingCatalog being credited for arena sightings that Google
  never confirmed.
- **Meta-phrased summaries rewritten** ("Jimmy Apples tweeted that…" → the claim itself), 150 claims; "As of DATE,"
  prefixes stripped at build time.
- **Daily pipeline now runs the prune check on new claims** (drops "Grok Web now has Weather cards"-type observations).
- Resolver: one batch rejected by OpenAI's bio-risk filter — those claims keep their previous verdict.
- Spend so far: ~$31 OpenAI (Luna re-grade ~$25, prune ~$1, benchmarks ~$4, Astra ~$2).

- **Astra blind audit** of 80 random un-audited verdicts: 68.8% outcome-bucket agreement with Luna (same as the earlier
  Opus figure → ~70% looks like the inherent ambiguity ceiling, not a pipeline defect). Disagreements roughly
  symmetric; Astra's verdict adopted where it differed (25 claims, marked audited). Method page states this.
- Evidence URLs: random sample of 60 → no 404s; ~half 403 (openai.com etc. block bots), so fabrication can't be fully
  ruled out but no sign of it.
- "Most credible pending" tab limited to the last 90 days (was dominated by old long-horizon business claims).
- Daily re-check cadence: not-yet-confirmable internal claims monthly (was fortnightly) → ~30 claims/day steady.
- Leaker blurbs refreshed against the current record (Luna, keeps Opus wording where still true; neutral pronouns);
  CI refreshes them every Monday.
- CI: deploy job was missing `pip install` (broke when build_site started importing resolve) → fixed; pushes touching
  data/ now redeploy.

- **Third Astra review (regressions)** → fixed: failed extractions now go to a retry queue (were silently lost after a
  catch-up); explicit `deadline_stated` from extraction (was the ±180d heuristic for new claims too); daily prune is
  drop-only (text corrections could leave lab/deadline stale) and only marks claims checked when a decision came back;
  journalist-scoop classification centralised (daily and site disagreed); independently-confirmed journalist scoops no
  longer excluded (the same-day-only rule now applies just to code/arena finds); event grouping is
  outcome-independent (lab + ISO week of the event, or story id); repeats show the original's status and are
  un-repeated if the original is pruned; resolver acceptance gate (invalid dates / still-inconsistent retries dropped,
  first-pass grades kept if a retry fails); false claims get one last check after the grace window; verdict rules
  applied in one consistent order; corroboration excludes relays/repeats/already-public contributors; run-wide
  extraction time budget + per-search error isolation; method copy matches the code.

- Pruned 49 non-AI claims (iPads, Xbox layoffs, Threads, Find My…) with a sharper scope definition, now also used by
  the daily filter. Dates in the future (a grader typo'd 2025→2026) are rejected; displayed lead capped at "over a year"
  (multi-year leads usually meant the grader latched onto a looser later event).
- Ranking threshold is now 5+ distinct settled *stories* (event groups), not 5 claims.
- Tested a looser wider-X search (150 likes): mostly relays/engagement bait → kept the 400-like bar.
- Astra audit of the 80 un-audited claims shown as leakers' "best calls"/"biggest misses" (what readers see first).

- That audit agreed only 40% — expected for the most extreme verdicts — and showed many "biggest misses" weren't leaks:
  explicit personal guesses ("nonzero chance…", "my prediction…"), an April-Fools riff. Policy sharpened (prune +
  resolver): a prediction *presented as information* is a claim; one *framed as the poster's own guess/odds* is not.
  Re-checked the 537 speculation-typed claims → 180 dropped. Rankings barely moved (robust).
- Spend tonight ≈ $86 (Luna ≈ $30, Astra ≈ $57) — stopped discretionary spending here to stay under $100.

- Astra audits of the claims readers see first (best calls / biggest misses; converged after 3 passes) and of the
  100 highest-significance hits/misses of ranked leakers. Agreement on these extremes is low (25–42%): Luna's errors
  cluster exactly where they're most visible, so targeted auditing there is the best use of budget.

- Loophole closed: launch-day posts by code sleuths/journalists ("OpenAI o3-pro today") counted as original finds
  because the company confirmed the same day. Now: officially announced on/before the post date → no credit, for
  everyone (257 claims). Real code-find leaks are confirmed later, so they're unaffected. Regression tests added
  (`python -m tests.test_scoring`, also run in CI before every build).

## Policy decisions I made (flag if you disagree)
- A prediction *presented as information* is a leak claim; one framed as the poster's own guess/odds is not.
- Same-day "hits" earn nothing unless it's an original find/scoop; code/arena finds additionally need later official
  confirmation (others seeing the same public listing doesn't confirm what it is).
- Journalists ranked separately; they're exempt from the automatic prune (couldn't reliably tell own-outlet scoops
  from relays) — the resolver's `not_a_claim` is the backstop.
- Untimed claims are never false just because time passed; the 180-day default is only a review horizon.
- Legitimacy is recalibrated on the backtest, so its range is compressed (~25–90).

## Decision for you (not made unilaterally)
**How should code/app-string finds that never ship be scored?** Right now "OpenAI is testing X" (found in app code) is
true if X launches and *unverifiable* (excluded) if it never does — so a sleuth who reports 10 strings of which 5 ship
scores ~100% on the settled ones (their lower "coverage" hints at this). Alternative: treat a code find as an implied
launch prediction → false if cancelled / not shipped within ~12 months. That would noticeably lower @btibor91,
@testingcatalog, @legit_api, @AiBattle_ (top 4). ~210 such claims; re-grading costs ~$3. A few older audited verdicts
already use the stricter reading (e.g. Tibor's shelved Sora-in-ChatGPT find is marked false), so there's some
inconsistency until this is decided.

## Running costs from here
- OpenAI: ~$0.5–1/day (Luna grading ~30–120 claims/day, extraction, prune); +~$0.05 on Mondays (blurb refresh).
- twitterapi.io: ~3–6k credits/day (~$0.05); ~400k left ≈ 2–3 months.
- One-off Astra audits ≈ $0.18/claim (`python -m scripts.astra_audit N seed --apply`, or `--displayed` /
  `--influential` for targeted passes).

## Open / ideas
- Astra #1 (no-hindsight dates) partly fixed (uses official date when present); a proper fix needs outcome history.
- Astra #14 (evidence provenance not verified) and #20 (no write lock) not addressed.
- Calibration is measured against the same grader's verdicts (shared-grader bias).
