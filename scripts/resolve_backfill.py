"""Resolve all unresolved claims (smart model for significant ones, fast model for minor). Streams + checkpoints."""
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from leakwatch import llm
from leakwatch.common import DATA, MODEL_FAST, MODEL_SMART, load_json, now_iso, save_json
from leakwatch.resolve import resolve_batch

WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 24


def main():
    claims = load_json(DATA / "claims.json")
    byid = {c["id"]: c for c in claims}
    todo = [c for c in claims if not c.get("resolution") and c["specificity"] >= 2]
    todo.sort(key=lambda c: (c["lab"], c["date"]))
    jobs = []
    big = [c for c in todo if c["significance"] >= 4]
    small = [c for c in todo if c["significance"] < 4]
    jb = [(MODEL_SMART, big[i:i + 8]) for i in range(0, len(big), 8)]
    js = [(MODEL_FAST, small[i:i + 8]) for i in range(0, len(small), 8)]
    # interleave so both models' rate limits are used at once
    for i in range(max(len(jb), len(js))):
        jobs += jb[i:i + 1] + js[i:i + 1]
    print(f"todo {len(todo)} claims in {len(jobs)} batches", flush=True)
    lock = threading.Lock()
    done = 0

    def run(job):
        model, b = job
        try:
            return resolve_batch(b, model, today="2026-10-10")
        except Exception as e:
            print("batch error:", str(e)[:200], flush=True)
            return {}

    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(run, j) for j in jobs]
        for f in as_completed(futs):
            res = f.result()
            with lock:
                for k, v in res.items():
                    if k in byid:
                        v.pop("id", None)
                        v["resolved_at"] = now_iso()
                        byid[k]["resolution"] = v
                done += 1
                if done % 20 == 0 or done == len(jobs):
                    save_json(DATA / "claims.json", claims)
                    print(f"{done}/{len(jobs)} batches, usage={llm.USAGE}", flush=True)
    save_json(DATA / "claims.json", claims)


if __name__ == "__main__":
    main()
