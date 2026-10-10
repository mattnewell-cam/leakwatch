"""Compare benchmark graders. Gold = unanimous bucket, else adjudicated verdict (data/cache/bench/adj_*.json).

python -m scripts.bench_compare            -> agreement table (+ writes adjudication packs for disagreements)
"""
import glob
import json
import random
from collections import Counter

from leakwatch.common import DATA, load_json, save_json

B = DATA / "cache" / "bench"
BUCKET = {"true": "hit", "mostly_true": "hit", "partly_true": "partly", "false": "miss"}
GRADERS = ["gpt54", "luna", "haiku", "opus"]


def bucket(v):
    return BUCKET.get(v, "excluded")


def load_grader(name):
    if name in ("gpt54", "luna"):
        d = load_json(B / f"{name}.json", {})
        return {k: v for k, v in (d.get("results") or {}).items()}
    out = {}
    for f in glob.glob(str(B / f"{name}_*.json")):
        try:
            for r in json.load(open(f, encoding="utf-8"))["results"]:
                out[r["id"]] = r
        except Exception as e:
            print("bad file", f, e)
    return out


def main():
    ids = load_json(B / "sample_ids.json")
    g = {n: load_grader(n) for n in GRADERS}
    for n in GRADERS:
        print(f"{n}: {len(g[n])} graded")
    adj = {}
    for f in glob.glob(str(B / "adj_out_*.json")):
        for r in json.load(open(f, encoding="utf-8"))["results"]:
            adj[r["id"]] = r["verdict"]
    full = [i for i in ids if all(i in g[n] for n in GRADERS)]
    gold, need = {}, []
    for i in full:
        bs = {bucket(g[n][i]["verdict"]) for n in GRADERS}
        if len(bs) == 1:
            # same bucket: exact gold = majority exact verdict (no single grader privileged)
            cnt = Counter(g[n][i]["verdict"] for n in GRADERS).most_common()
            gold[i] = cnt[0][0]
        elif i in adj:
            gold[i] = adj[i]
        else:
            need.append(i)
    print(f"{len(full)} fully graded; unanimous bucket {sum(1 for i in full if i in gold and i not in adj)}; "
          f"adjudicated {len(adj)}; awaiting adjudication {len(need)}")
    if need and not adj:
        byid = {c["id"]: c for c in load_json(DATA / "claims.json")}
        random.seed(1)
        items = []
        for i in need:
            c = byid[i]
            opts = [{"verdict": g[n][i]["verdict"], "public_date": g[n][i].get("public_date"),
                     "explanation": g[n][i].get("explanation", "")} for n in GRADERS]
            random.shuffle(opts)
            items.append({"id": i, "handle": c["handle"], "claim_date": c["date"][:10], "claim": c["claim"],
                          "resolve_by": c.get("resolve_by"), "source_type": c.get("source_type"),
                          "tweets": [t["text"][:700] for t in c.get("tweets", [])[:2]] or c.get("quote"),
                          "grader_opinions": {chr(65 + k): o for k, o in enumerate(opts)}})
        n_packs = max(1, (len(items) + 24) // 25)
        for k in range(n_packs):
            save_json(B / f"adj_pack_{k}.json", items[k::n_packs])
        print(f"wrote {n_packs} adjudication packs")
        return
    if not gold:
        return
    print(f"\nAgreement with gold on {len(gold)} claims:")
    print(f"{'grader':8} {'bucket':>7} {'exact':>7}  hit->miss/excl errors")
    for n in GRADERS:
        b = sum(bucket(g[n][i]["verdict"]) == bucket(v) for i, v in gold.items()) / len(gold)
        e = sum(g[n][i]["verdict"] == v for i, v in gold.items()) / len(gold)
        conf = Counter((bucket(v), bucket(g[n][i]["verdict"])) for i, v in gold.items()
                       if bucket(v) != bucket(g[n][i]["verdict"]))
        print(f"{n:8} {b:7.1%} {e:7.1%}  {dict(conf.most_common(4))}")
    save_json(B / "gold.json", gold)


if __name__ == "__main__":
    main()
