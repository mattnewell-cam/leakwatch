"""Compute resolver-vs-auditor agreement on a blind random sample (pack_t*/out_t*) -> data/audit_stats.json"""
import glob, json, sys
from leakwatch.common import DATA, now_iso, save_json

PREFIX = sys.argv[1] if len(sys.argv) > 1 else "t"
BUCKET = {"true": "hit", "mostly_true": "hit", "partly_true": "partly", "false": "miss"}


def main():
    n = exact = bucket = 0
    for f in sorted(glob.glob(str(DATA / "cache" / "audit" / f"out_{PREFIX}*.json"))):
        out = json.load(open(f, encoding="utf-8"))
        pack = json.load(open(f.replace("out_", "pack_"), encoding="utf-8"))
        orig = {c["id"]: c["resolver_verdict"] for l in pack["leakers"] for c in l["claims_to_audit"]}
        for a in out["claims"]:
            if a["id"] not in orig:
                continue
            n += 1
            exact += a["verdict"] == orig[a["id"]]
            bucket += BUCKET.get(a["verdict"], "excluded") == BUCKET.get(orig[a["id"]], "excluded")
    stats = {"sample_n": n, "exact_agreement": round(exact / n, 3), "bucket_agreement": round(bucket / n, 3),
             "computed_at": now_iso()}
    save_json(DATA / "audit_stats.json", stats)
    print(stats)


if __name__ == "__main__":
    main()
