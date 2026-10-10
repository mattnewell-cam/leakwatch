"""Random-sample audit packs of NOT-yet-audited resolved claims, to measure resolver/auditor agreement."""
import random
import sys

from leakwatch.common import DATA, load_json, save_json

N_PACKS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
PER_PACK = int(sys.argv[2]) if len(sys.argv) > 2 else 40


def main():
    claims = load_json(DATA / "claims.json")
    pool = [c for c in claims if c.get("resolution") and not c["resolution"].get("vetted")
            and c["resolution"]["verdict"] in ("true", "mostly_true", "partly_true", "false", "already_public")]
    random.seed(2026)
    pick = random.sample(pool, min(len(pool), N_PACKS * PER_PACK))
    for i in range(N_PACKS):
        chunk = pick[i * PER_PACK:(i + 1) * PER_PACK]
        by = {}
        for c in chunk:
            r = c["resolution"]
            by.setdefault(c["handle"], []).append({
                "id": c["id"], "date": c["date"][:10], "claim": c["claim"], "lab": c["lab"],
                "resolve_by": c.get("resolve_by"), "significance": c["significance"],
                "tweet": " || ".join(t["text"][:500] for t in c.get("tweets", [])[:2]) or c.get("quote"),
                "origin": c.get("origin"), "resolver_verdict": r["verdict"], "public_date": r.get("public_date"),
                "explanation": r.get("explanation"), "evidence": [e["url"] for e in r.get("evidence", [])],
                "confidence": r.get("confidence")})
        save_json(DATA / "cache" / "audit" / f"pack_s{i}.json",
                  {"leakers": [{"handle": h, "claims_to_audit": v} for h, v in by.items()]})
    print(f"{N_PACKS} sample packs from pool of {len(pool)}")


if __name__ == "__main__":
    main()
