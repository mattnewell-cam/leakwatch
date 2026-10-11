"""Rewrite meta-phrased claim summaries ("X tweeted that...", "The author claimed...") as direct statements.

python -m scripts.clean_claim_text [--apply]
"""
import re
import sys

from leakwatch.common import DATA, MODEL_FAST, load_json, save_json
from leakwatch.llm import S, arr, call_json, obj

META = re.compile(r"^(the author|the poster|according to the author|a \w+ commenter|reddit|on \d{4}-\d{2}-\d{2},? "
                  r"the (author|poster)|[@\w][\w .'-]{0,30} (tweeted|posted|claimed|said|speculated|wrote|suggested|asserted|thinks|believes|noted|"
                  r"wondered|predicted|expects|reported|argued|implied|hinted)\b)",
                  re.I)
SCHEMA = obj({"items": arr(obj({"id": S, "claim": S}))})
SYS = """Rewrite each leak-claim summary as a direct, standalone statement of WHAT IS CLAIMED (not who said it):
"Jimmy Apples tweeted that OpenAI achieved AGI internally" -> "OpenAI has achieved AGI internally."
"The author claimed Gemini 3 launches on 2025-10-22" -> "Google will launch Gemini 3 on 2025-10-22."
Keep every detail, date and hedge ("reportedly", "may") exactly; don't add or remove information. If the summary
describes OTHER people discussing the account (e.g. a forum recording what they said), still extract the claim itself."""


def main():
    claims = load_json(DATA / "claims.json")
    todo = [c for c in claims if not c.get("pruned") and META.search(c["claim"])]
    print("meta-phrased:", len(todo))
    out = {}
    for i in range(0, len(todo), 30):
        b = todo[i:i + 30]
        r = call_json(MODEL_FAST, SYS, "\n".join(f"{c['id']}: {c['claim']}" for c in b), SCHEMA, name="clean")
        allowed = {c["id"] for c in b}
        out.update({x["id"]: x["claim"] for x in r["items"] if x["id"] in allowed and x["claim"].strip()})
    for c in todo[:12]:
        print(f"  {c['claim'][:100]}\n   -> {out.get(c['id'], '(none)')[:100]}")
    if "--apply" in sys.argv:
        for c in claims:
            if c["id"] in out:
                c.setdefault("claim_v1", c["claim"])
                c["claim"] = out[c["id"]]
        save_json(DATA / "claims.json", claims)
        print("applied", len(out))


if __name__ == "__main__":
    main()
