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
PRIOR_A, PRIOR_B = 2.0, 2.0
IMPACT_K = 8.0
UNKNOWN_PRIOR = 0.35  # accounts with no track record


def d(s):
    return date.fromisoformat(s[:10]) if s else None


def is_scoop(c):
    """Original finds whose same-day press coverage IS the leak: a journalist's own reporting, or a code/A-B-test find
    (coverage of the find is not prior public knowledge). Lead time for these runs to official confirmation."""
    if c.get("source_type") == "code_or_testing_evidence":
        return True
    return c.get("source_type") == "journalism" and c.get("_category") == "journalist"


def effective_verdict(c):
    """Normalize the resolver verdict: true-ish claims that weren't ahead of public knowledge become already_public."""
    r = c.get("resolution") or {}
    v = r.get("verdict") or "pending"
    if v == "already_public":
        # must point to an earlier public source; original finds/scoops need a strictly earlier one
        pd = (r.get("public_date") or "")[:10]
        if not pd or pd > c["date"][:10] or (is_scoop(c) and pd >= c["date"][:10]):
            return "unverifiable"
    if v in ("true", "mostly_true", "partly_true") and r.get("public_date"):
        try:
            pd = d(r["public_date"])
            # someone else had it first -> no credit (applies to scoops/code finds too)
            if pd < d(c["date"]):
                return "already_public"
            # same-day "hits" can't be told apart from reacting to the launch -> no credit, no penalty
            # (except original finds/scoops, whose same-day coverage IS the leak)
            if pd == d(c["date"]) and not is_scoop(c):
                return "already_public"
        except ValueError:
            pass
    if v == "unverifiable" and review_until(c) > date.today().isoformat():
        return "pending"        # can't confirm yet, but it's still within its window
    if c.get("specificity", 3) <= 1 and v == "pending":
        return "unfalsifiable"
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
    ref, kind = r.get("public_date"), "public"
    try:
        if is_scoop(c) or (ref and d(ref) <= d(c["date"])):
            if r.get("official_date"):
                ref, kind = r["official_date"], "official"
    except ValueError:
        return None, None
    return (ref[:10], kind) if ref else (None, None)


def lead_days(c):
    """Days between the claim and public knowledge (for original finds/scoops: official confirmation)."""
    v = effective_verdict(c)
    if v not in VALUE or VALUE[v] == 0:
        return None
    ref, _ = lead_ref(c)
    try:
        return max(0, (d(ref) - d(c["date"])).days) if ref else None
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


UNTRACKED_PRIOR = (UNKNOWN_PRIOR * 4, (1 - UNKNOWN_PRIOR) * 4)   # same strength as Beta(2,2), sceptical mean


def event_key(c):
    """Claims settled by the same event (same lab + same confirmation/deadline date) are one piece of evidence:
    five details about one launch shouldn't count as five independent hits."""
    r = c.get("resolution") or {}
    v = effective_verdict(c)
    if v in ("true", "mostly_true", "partly_true"):
        return (c["lab"], "hit", (r.get("official_date") or r.get("public_date") or c["date"])[:10])
    return (c["lab"], "miss", (c.get("resolve_by") or c["date"])[:10], c["id"] if not c.get("resolve_by") else "")


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
    p = min(0.97, max(0.03, p))
    return round(p * 100), comps
