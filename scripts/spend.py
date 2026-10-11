"""Print estimated OpenAI spend from the local ledger since a unix timestamp (default: all)."""
import json, sys, collections
from leakwatch.common import DATA
since = float(sys.argv[1]) if len(sys.argv) > 1 else 0
tot = collections.Counter()
try:
    for line in open(DATA / "cache" / "spend.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r["t"] >= since: tot[r["model"]] += r["cost"]
except FileNotFoundError:
    pass
print({k: round(v, 2) for k, v in tot.items()}, "total $", round(sum(tot.values()), 2))
