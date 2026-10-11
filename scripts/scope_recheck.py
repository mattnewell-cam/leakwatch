"""Re-check that every live claim is about AI; prune the rest. python -m scripts.scope_recheck [--apply]"""
import sys
from concurrent.futures import ThreadPoolExecutor

from leakwatch.common import DATA, MODEL_FAST, load_json, save_json
from leakwatch.llm import S, arr, call_json, obj

SCHEMA = obj({"off_topic_ids": arr(S)})
SYS = """This site tracks leaks about AI: AI models and their capabilities/releases, AI products and features, AI labs
(OpenAI, Anthropic, Google DeepMind/Gemini, xAI, Meta AI, Mistral, DeepSeek, ...) and their people, funding, deals,
IPOs and legal fights, AI chips/compute/data centres, and government AI policy.
Return the ids of claims that are NOT about AI - e.g. iPhone/Mac/Watch/Vision Pro hardware, modems, displays, AirPods,
general Apple/Google/Microsoft product news unrelated to AI, Xbox/gaming, Tesla cars, SpaceX launches, crypto,
politics unrelated to AI, social-media product changes unrelated to AI. Big-tech claims ARE in scope when they're about
AI (Siri/Apple Intelligence, Gemini in Android, Copilot, AI deals, AI chips). When unsure, keep it (don't list it)."""


def main():
    claims = load_json(DATA / "claims.json")
    live = [c for c in claims if not c.get("pruned")]
    batches = [live[i:i + 60] for i in range(0, len(live), 60)]

    def run(b):
        allowed = {c["id"] for c in b}
        try:
            r = call_json(MODEL_FAST, SYS, "\n".join(f"{c['id']}: [{c['lab']}] {c['claim'][:300]}" for c in b),
                          SCHEMA, name="scope")
            return [i for i in r["off_topic_ids"] if i in allowed]
        except Exception as e:
            print("err", str(e)[:150])
            return []
    off = set()
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(run, batches):
            off.update(r)
    byid = {c["id"]: c for c in claims}
    for i in list(off)[:25]:
        print(f"  OFF [{byid[i]['lab']}] @{byid[i]['handle']} | {byid[i]['claim'][:110]}")
    print(f"off-topic: {len(off)} of {len(live)}")
    if "--apply" in sys.argv:
        for i in off:
            byid[i]["pruned"] = "out_of_scope: not about AI"
        save_json(DATA / "claims.json", claims)
        print("applied")


if __name__ == "__main__":
    main()
