"""Regression tests for the scoring rules (no network, no API). Run: python -m tests.test_scoring"""
from datetime import date, timedelta

from leakwatch import scoring as sc
from leakwatch.resolve import _consistent, deadline_stated

TODAY = date.today()


def day(n):
    return (TODAY + timedelta(days=n)).isoformat()


def claim(**kw):
    c = {"id": kw.pop("id", "x-1"), "handle": kw.pop("handle", "someone_untracked"), "date": kw.pop("date", day(-100)),
         "lab": kw.pop("lab", "OpenAI"), "specificity": kw.pop("specificity", 3), "significance": 3,
         "source_type": kw.pop("source_type", "insider")}
    res = kw.pop("res", None)
    if res:
        c["resolution"] = res
    c.update(kw)
    return c


def test_novelty():
    # someone else had it earlier -> already_public
    assert sc.effective_verdict(claim(res={"verdict": "true", "public_date": day(-120)})) == "already_public"
    # same-day hit from an insider -> already_public (can't tell from reacting)
    assert sc.effective_verdict(claim(date=day(-100), res={"verdict": "true", "public_date": day(-100)})) == "already_public"
    # genuinely early -> stays true
    assert sc.effective_verdict(claim(res={"verdict": "true", "public_date": day(-80)})) == "true"


def test_code_finds():
    base = dict(source_type="code_or_testing_evidence", date=day(-100))
    # same-day coverage only, no official confirmation -> unverifiable (window passed: claim is >1y? no -> pending)
    old = dict(base, date=day(-500))
    assert sc.effective_verdict(claim(**old, res={"verdict": "true", "public_date": day(-500)})) == "unverifiable"
    # with later official confirmation -> true
    assert sc.effective_verdict(claim(**old, res={"verdict": "true", "public_date": day(-500),
                                                  "official_date": day(-450)})) == "true"
    # someone else published first -> already_public even for a code find
    assert sc.effective_verdict(claim(**old, res={"verdict": "true", "public_date": day(-520)})) == "already_public"
    # launch-day relay ("o3-pro today"): officially announced the same day -> no credit, even for a code sleuth
    assert sc.effective_verdict(claim(**old, res={"verdict": "true", "public_date": day(-500),
                                                  "official_date": day(-500)})) == "already_public"


def test_invalid_already_public():
    # already_public must cite an earlier date; otherwise it's not trusted
    c = claim(date=day(-500), res={"verdict": "already_public", "public_date": day(-400)})
    assert sc.effective_verdict(c) == "unverifiable"
    assert not _consistent(c, c["resolution"])
    good = claim(date=day(-500), res={"verdict": "already_public", "public_date": day(-510)})
    assert _consistent(good, good["resolution"])


def test_future_dates_rejected():
    c = claim(res={"verdict": "true", "public_date": day(-80), "official_date": day(30)})
    assert not _consistent(c, c["resolution"])
    assert sc.lead_ref(c)[1] == "public"            # future official date ignored


def test_review_window():
    # young unverifiable claim -> pending; old one stays unverifiable
    assert sc.effective_verdict(claim(date=day(-30), res={"verdict": "unverifiable"})) == "pending"
    assert sc.effective_verdict(claim(date=day(-400), res={"verdict": "unverifiable"})) == "unverifiable"
    # vague + pending -> unfalsifiable (also when it arrived via the unverifiable->pending path)
    assert sc.effective_verdict(claim(date=day(-30), specificity=1, res={"verdict": "unverifiable"})) == "unfalsifiable"


def test_deadline_stated():
    assert not deadline_stated(claim(date=day(-200), resolve_by=day(-20)))           # +180d default
    assert deadline_stated(claim(date=day(-200), resolve_by=day(-190)))              # explicit
    assert deadline_stated(claim(date=day(-200), resolve_by=day(-20), deadline_stated=True))
    assert not deadline_stated(claim(date=day(-200), resolve_by=day(-190), deadline_stated=False))


def test_event_grouping_counts_once():
    hits = [claim(id=f"h{i}", date=day(-100), res={"verdict": "true", "public_date": day(-90)}) for i in range(5)]
    groups = sc.grouped(hits)
    assert len(groups) == 1 and abs(groups[0][1] - 1.0) < 1e-9
    # a miss about the same launch week lands in the same group
    miss = claim(id="m1", date=day(-100), resolve_by=day(-90), deadline_stated=True, res={"verdict": "false"})
    assert len(sc.grouped(hits + [miss])) == 1


def test_lead_capped():
    c = claim(date=day(-900), res={"verdict": "true", "public_date": day(-100)})
    assert sc.lead_days(c) == 365


def test_legitimacy_bounds():
    s, comps = sc.legitimacy(claim(), [], tracked=False)
    assert 5 <= s <= 95 and comps[-1]["label"].startswith("Calibration")


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            n += 1
    print(f"{n} scoring tests passed")
