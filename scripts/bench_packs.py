"""Build Claude grader packs + prompt for the model benchmark (same rubric as the API resolver)."""
from leakwatch.common import DATA, ROOT, load_json, save_json
from leakwatch.resolve import SYSTEM, _category

B = DATA / "cache" / "bench"
ids = load_json(B / "sample_ids.json")
byid = {c["id"]: c for c in load_json(DATA / "claims.json")}
for i in range(12):
    chunk = [byid[x] for x in ids[i * 25:(i + 1) * 25]]
    save_json(B / f"cpack_{i}.json", [{
        "id": c["id"], "handle": c["handle"], "account_type": _category(c["handle"]), "claim_date": c["date"][:10],
        "lab": c["lab"], "resolve_by": c.get("resolve_by"), "claim": c["claim"], "source_type": c.get("source_type"),
        "tweets": [{"date": t["created_at"][:16], "text": t["text"][:700]} for t in c.get("tweets", [])[:2]] or None,
        "quote": c.get("quote"), "source_url": c.get("source_url")} for c in chunk])
bench = str(B)
prompt = (
    "You are grading AI-industry leak claims for LeakWatch, a public leaker-accuracy leaderboard. This is a model "
    "benchmark: grade independently and carefully.\n\n"
    f"INPUT: {bench}\cpack_N.json (25 claims), where N is given below.\n"
    f"RESOURCES: the official event timeline {DATA}\events.json (~330 dated lab events; Grep it by model/company "
    "name), your own knowledge, WebSearch and WebFetch. The search budget is shared across many parallel graders: use "
    "AT MOST 10 WebSearch calls in total (prioritise claims the timeline can't settle); WebFetch is fine for checking "
    "specific pages.\n\nRUBRIC (identical to the one the other graders get):\n---\n" + SYSTEM.format(today="2026-10-10") +
    "\n---\n\n"
    f"OUTPUT: write {bench}\MODEL_N.json (MODEL and N given below) as JSON: "
    '{"results": [{"id": "...", "verdict": "true|mostly_true|partly_true|false|pending|already_public|unverifiable", '
    '"public_date": "YYYY-MM-DD or null", "official_date": "YYYY-MM-DD or null", "explanation": "1-2 sentences", '
    '"confidence": "low|medium|high"}]} with one entry for every claim. Reply only "done MODEL N".\n')
(ROOT / "scripts" / "bench_grader_prompt.md").write_text(prompt, encoding="utf-8")
print("ok", len(prompt))
