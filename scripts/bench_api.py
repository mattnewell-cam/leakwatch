"""Grade the benchmark sample with an API model: python -m scripts.bench_api <model> <out_name>"""
import sys, time, json
from concurrent.futures import ThreadPoolExecutor
from leakwatch.common import DATA, load_json, save_json
from leakwatch.resolve import resolve_batch
from leakwatch import llm

def main():
    model, name = sys.argv[1], sys.argv[2]
    ids = load_json(DATA / "cache" / "bench" / "sample_ids.json")
    byid = {c["id"]: c for c in load_json(DATA / "claims.json")}
    claims = [byid[i] for i in ids]
    claims_sorted = sorted(claims, key=lambda c: (c["lab"], c["date"]))
    batches = [claims_sorted[i:i + 8] for i in range(0, len(claims_sorted), 8)]
    t = time.time(); out = {}
    def run(b):
        try: return resolve_batch(b, model, today="2026-10-10")
        except Exception as e: print("err", str(e)[:150], flush=True); return {}
    with ThreadPoolExecutor(12) as ex:
        for r in ex.map(run, batches): out.update(r)
    save_json(DATA / "cache" / "bench" / f"{name}.json", {"model": model, "secs": round(time.time() - t), "usage": dict(llm.USAGE), "results": out})
    print(name, len(out), "secs", round(time.time() - t), llm.USAGE, flush=True)

if __name__ == "__main__":
    main()
