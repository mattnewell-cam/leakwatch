"""Scoring: per-claim outcome values, per-leaker credibility / impact / Leak Score, and per-claim legitimacy.

Design notes (also shown on the site's Methodology page):
- Accuracy is a Bayesian posterior (Beta(2,2) prior) over weighted resolved claims, so a handful of lucky hits can't
  top the board. Specific claims weigh more than vague ones; hedged or second-hand claims weigh less.
- Claims whose info was already public when tweeted earn nothing (and don't count against accuracy either), but feed a
  "stale rate" that's shown on profiles.
- Impact rewards correct claims that were big (significance) and early (lead time before public confirmation).
- Leak Score = credibility^1.5 x (1 - exp(-impact / K)) - you need both a good hit rate AND a body of significant, early,
  correct calls.
- Legitimacy of an individual claim is computed only from the leaker's record as it stood when the claim was made
  (no hindsight), adjusted for claim type, specificity, hedging and corroboration.
"""
import math
from collections import defaultdict
from datetime import date

VALUE = {"true": 1.0, "mostly_true": 0.8, "partly_true": 0.4, "false": 0.0}
SPEC_W = {1: 0.3, 2: 0.6, 3: 1.0, 4: 1.3, 5: 1.6}
SIG_W = {1: 0.25, 2: 0.5, 3: 1.0, 4: 2.0, 5: 3.0}
PRIOR_A, PRIOR_B = 4.0, 4.0     # prior worth 8 claims: chosen by backtest Brier (scripts/tune_prior.py)
IMPACT_K = 8.0
UNKNOWN_PRIOR = 0.35  # accounts with no track record
CALIB_A, CALIB_B = 0.229, 0.683   # legitimacy recalibration (see legitimacy())


def d(s):
    return date.fromisoformat(s[:10]) if s else None


def is_scoop(c):
    """Original finds whose same-day press coverage IS the leak: a journalist's own reporting, or a code/A-B-test find
    (coverage of the find is not prior public knowledge). Lead time for these runs to official confirmation.
    Uses the same account classification everywhere (daily, build, resolver)."""
    if c.get("source_type") == "code_or_testing_evidence":
        return True
    if c.get("source_type") != "journalism":
        return False
    from .resolve import _category
    return _category(c["handle"]) == "journalist"


def _valid_date(s):
    """A real calendar date that isn't in the future (graders occasionally typo a year)."""
    try:
        x = d(s) if s else None
    except ValueError:
        return None
    return x if x and x <= date.today() else None


def effective_verdict(c):
    """Normalize the resolver verdict, applying each rule in order to one working verdict:
    1. novelty: true-ish claims that weren't ahead of public knowledge -> already_public; an already_public verdict
       without a valid earlier date -> unverifiable
    2. code/arena finds whose only confirmation is same-day coverage of the find itself -> unverifiable
    3. unverifiable but still inside its review window -> pending
    4. pending but too vague to ever check -> unfalsifiable"""
    r = c.get("resolution") or {}
    v = r.get("verdict") or "pending"
    cd = _valid_date(c["date"])
    pd = _valid_date(r.get("public_date"))
    if v == "already_public":
        if not pd or not cd or pd > cd or (is_scoop(c) and pd >= cd):
            v = "unverifiable"
    elif v in ("true", "mostly_true", "partly_true") and pd and cd:
        od = _valid_date(r.get("official_date"))
        if pd < cd:                                  # someone else had it first (applies to scoops too)
            v = "already_public"
        elif od and od <= cd:                        # officially announced that same day ("o3-pro today") - a
            v = "already_public"                     # launch-day relay, even from a code sleuth or journalist
        elif pd == cd and not is_scoop(c):           # same-day "hit" can't be told from reacting to the launch
            v = "already_public"
        elif (pd == cd and c.get("source_type") == "code_or_testing_evidence"
              and not _valid_date(r.get("official_date"))):
            # e.g. others seeing the same public arena listing - the attribution itself was never confirmed.
            # (journalists' scoops are exempt: the resolver already requires independent confirmation for them)
            v = "unverifiable"
    if v == "unverifiable" and review_until(c) > date.today().isoformat():
        v = "pending"                                # can't confirm yet, but it's still within its window
    if v == "pending" and c.get("specificity", 3) <= 1:
        v = "unfalsifiable"
    return v


def review_until(c):
    """The claim's own deadline if the poster gave one, else a 1-year review horizon (not attributed to the poster)."""
    from .resolve import deadline_stated
    if deadline_stated(c):
        return c["resolve_by"][:10]
    try:
        return date.fromordinal(d(c["date"]).toordinal() + 365).isoformat()
    except (TypeError, ValueError):
        return ""


def lead_ref(c):
    """(date, kind) the lead time is measured to: first public report, or official confirmation for original
    finds/scoops (and when the first report was same-day)."""
    r = c.get("resolution") or {}
    pub, off = _valid_date(r.get("public_date")), _valid_date(r.get("official_date"))
    ref, kind = pub, "public"
    if (is_scoop(c) or (pub and pub <= _valid_date(c["date"]))) and off:
        ref, kind = off, "official"
    return (ref.isoformat(), kind) if ref else (None, None)


def lead_days(c):
    """Days between the claim and public knowledge (for original finds/scoops: official confirmation)."""
    v = effective_verdict(c)
    if v not in VALUE or VALUE[v] == 0:
        return None
    ref, _ = lead_ref(c)
    try:
        return min(365, max(0, (d(ref) - d(c["date"])).days)) if ref else None   # >1y usually = a looser later event
    except ValueError:
        return None


def claim_weight(c):
    w = SPEC_W.get(c.get("specificity", 3), 1.0)
    if c.get("hedged"):
        w *= 0.7
    if c.get("cryptic"):
        w *= 0.85
    if c.get("source_type") == "relayed":
        w *= 0.8
    if c.get("origin") == "trawl":
        w *= 0.85
    conf = (c.get("resolution") or {}).get("confidence")
    if conf == "low":
        w *= 0.6
    return w


def resolved_on(c):
    """Date on which the outcome became knowable (for no-hindsight legitimacy)."""
    r = c.get("resolution") or {}
    v = effective_verdict(c)
    if v in ("true", "mostly_true", "partly_true") and (r.get("official_date") or r.get("public_date")):
        # knowable once independently confirmed: official confirmation if any, else first public report
        return (r.get("official_date") or r.get("public_date"))[:10]
    if v == "false":
        from .resolve import deadline_stated
        rb = c["resolve_by"][:10] if deadline_stated(c) else None
        fallback = date.fromordinal(d(c["date"]).toordinal() + 180).isoformat()
        return max(rb or fallback, c["date"][:10])
    return None


def posterior(pairs, prior=(PRIOR_A, PRIOR_B)):
    """pairs: [(weight, value)] -> (mean, low, effective_n)"""
    sw = sum(w for w, _ in pairs)
    swv = sum(w * v for w, v in pairs)
    a, b = prior[0] + swv, prior[1] + (sw - swv)
    m = a / (a + b)
    sd = math.sqrt(m * (1 - m) / (a + b + 1))
    return m, max(0.0, m - sd), sw


UNTRACKED_PRIOR = (UNKNOWN_PRIOR * 8, (1 - UNKNOWN_PRIOR) * 8)   # same strength, sceptical mean


def event_key(c):
    """Claims settled by the same event (same lab + same confirmation/deadline date) are one piece of evidence:
    five details about one launch shouldn't count as five independent hits."""
    # outcome-independent: hits and misses about the same launch land in the same group. Approximation: same lab +
    # same ISO week of the event the claim is about (confirmation date for hits, stated deadline for misses, else the
    # claim date); daily-linked story ids take precedence.
    if c.get("story_id"):
        return ("story", c["story_id"])
    r = c.get("resolution") or {}
    from .resolve import deadline_stated
    if effective_verdict(c) in ("true", "mostly_true", "partly_true"):
        ref = r.get("official_date") or r.get("public_date") or c["date"]
    else:
        ref = c["resolve_by"] if deadline_stated(c) else c["date"]
    t = _valid_date(ref) or _valid_date(c["date"])
    y, w, _ = t.isocalendar()
    return (c["lab"], y, w)


def grouped(claims):
    """-> list of (weight, value, members) per event: weight = max member weight, value = weighted mean."""
    groups = defaultdict(list)
    for c in claims:
        v = effective_verdict(c)
        if v in VALUE:
            groups[event_key(c)].append((claim_weight(c), VALUE[v], c))
    out = []
    for g in groups.values():
        sw = sum(w for w, _, _ in g)
        out.append((max(w for w, _, _ in g), sum(w * v for w, v, _ in g) / sw if sw else 0.0, [c for _, _, c in g]))
    return out


def lead_factor(ld):
    if ld is None:
        return 0.6
    return 0.5 + 0.5 * min(max(ld, 0), 60) / 60 + (0.25 if ld > 60 else 0)


def lab_credibility(groups_lab, overall_mean, k=4.0):
    """Per-lab accuracy shrunk continuously toward the account's overall accuracy (no hard threshold)."""
    return posterior([(w, v) for w, v, _ in groups_lab], prior=(k * overall_mean, k * (1 - overall_mean)))[0]


def leaker_stats(claims, tracked=True):
    """claims: all claims of one leaker (with resolution). Returns stats dict."""
    prior = (PRIOR_A, PRIOR_B) if tracked else UNTRACKED_PRIOR
    counts = defaultdict(int)
    for c in claims:
        counts[effective_verdict(c)] += 1
    groups = grouped(claims)
    m, low, n_eff = posterior([(w, v) for w, v, _ in groups], prior)
    impact, leads = 0.0, []
    by_lab = defaultdict(list)
    for w, v, members in groups:
        by_lab[members[0]["lab"]].append((w, v, members))
        if v > 0:
            best = 0.0
            for c in members:
                ld = lead_days(c)
                if ld is not None:
                    leads.append(ld)
                vv = VALUE[effective_verdict(c)]
                best = max(best, vv * SIG_W.get(c.get("significance", 3), 1) * lead_factor(ld) * min(1.0, claim_weight(c)))
            impact += best
    n = len(claims)
    resolved = sum(counts[k] for k in VALUE)
    open_or_unsettled = counts["pending"] + counts["unverifiable"]
    hits = counts["true"] + counts["mostly_true"]
    score = 100 * (m ** 1.5) * (1 - math.exp(-impact / IMPACT_K))
    leads.sort()
    return {
        "n_claims": n,
        "n_resolved": resolved,
        "n_events": len(groups),
        "n_true": counts["true"], "n_mostly_true": counts["mostly_true"], "n_partly_true": counts["partly_true"],
        "n_false": counts["false"], "n_pending": counts["pending"], "n_unverifiable": counts["unverifiable"],
        "n_already_public": counts["already_public"], "n_unfalsifiable": counts["unfalsifiable"],
        "hit_rate_raw": round(hits / resolved, 3) if resolved else None,
        # share of checkable claims that have actually been settled (low coverage = accuracy rests on a small slice)
        "coverage": round(resolved / (resolved + open_or_unsettled), 3) if resolved + open_or_unsettled else None,
        "credibility": round(m, 3),
        "credibility_low": round(low, 3),
        "effective_n": round(n_eff, 1),
        "impact": round(impact, 2),
        "leak_score": round(score, 1),
        "median_lead_days": leads[len(leads) // 2] if leads else None,
        "stale_rate": round(counts["already_public"] / n, 3) if n else None,
        "vague_rate": round(sum(1 for c in claims if c.get("specificity", 3) <= 2) / n, 3) if n else None,
        "by_lab": {lab: {"n": sum(len(g[2]) for g in gs), "credibility": round(lab_credibility(gs, m), 3),
                         "hits": sum(1 for g in gs for c in g[2] if VALUE[effective_verdict(c)] >= 0.8),
                         "misses": sum(1 for g in gs for c in g[2] if VALUE[effective_verdict(c)] == 0)}
                   for lab, gs in by_lab.items()},
    }


def credibility_as_of(claims, when, lab=None, tracked=True):
    """Leaker credibility using only claims made and resolved strictly before `when` (YYYY-MM-DD)."""
    prior = (PRIOR_A, PRIOR_B) if tracked else UNTRACKED_PRIOR
    known = [c for c in claims if c["date"][:10] < when and (resolved_on(c) or "9999") < when]
    groups = grouped(known)
    m, low, n = posterior([(w, v) for w, v, _ in groups], prior)
    if lab:
        gl = [g for g in groups if g[2][0]["lab"] == lab]
        if gl:
            m = lab_credibility(gl, m)
    return m, n


SOURCE_ADJ = {"code_or_testing_evidence": 0.10, "journalism": 0.06, "insider": 0.0, "relayed": -0.06,
              "speculation": -0.15}


def legitimacy(claim, history, tracked=True, corroboration=0.0, plausibility=None):
    """0-100 score for how likely a claim is to be true, from the leaker's track record at claim time."""
    when = claim["date"][:10]
    # every account learns from its own record; untracked accounts just start from a more sceptical prior
    base, n_eff = credibility_as_of(history or [], when, claim.get("lab"), tracked=tracked)
    comps = [{"label": "Track record at time of claim" if n_eff else "No track record (prior)",
              "value": round(base * 100)}]
    p = base
    adj = SOURCE_ADJ.get(claim.get("source_type"), 0)
    if adj:
        comps.append({"label": f"Claim type: {claim.get('source_type', '').replace('_', ' ')}", "delta": round(adj * 100)})
        p += adj
    if claim.get("hedged"):
        p -= 0.05
        comps.append({"label": "Hedged / caveated", "delta": -5})
    spec = claim.get("specificity", 3)
    if spec <= 1:
        p = 0.5 * p + 0.5 * 0.3
        comps.append({"label": "Too vague to really verify", "delta": None})
    elif spec >= 4 and base >= 0.6:
        p += 0.03
        comps.append({"label": "Specific claim from a reliable source", "delta": 3})
    if corroboration:
        p += corroboration
        comps.append({"label": "Corroborated by other tracked leakers", "delta": round(corroboration * 100)})
    if plausibility is not None:
        delta = (plausibility - 0.5) * 0.2
        p += delta
        comps.append({"label": "Plausibility check (model judgement)", "delta": round(delta * 100)})
    # linear recalibration fitted on the no-hindsight backtest (held-out Brier 0.122 -> 0.113): the heuristic above
    # spreads too wide - low scores still come true ~40% of the time, top scores ~86%
    raw = min(0.97, max(0.03, p))
    q = min(0.95, max(0.05, CALIB_A + CALIB_B * raw))
    comps.append({"label": "Calibration to past outcomes", "delta": round((q - raw) * 100)})
    return round(q * 100), comps
