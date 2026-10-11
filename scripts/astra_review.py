"""Ask GPT-6 Astra to review the codebase (or a focus area). python -m scripts.astra_review [focus text]"""
import sys
import time

import requests

from leakwatch.common import OPENAI_KEY, ROOT
from leakwatch.llm import _log_spend

FILES = ["leakwatch/common.py", "leakwatch/twitter.py", "leakwatch/llm.py", "leakwatch/extract.py", "leakwatch/resolve.py",
         "leakwatch/scoring.py", "leakwatch/daily.py", "scripts/build_site.py", "scripts/import_backfill.py",
         "scripts/prune_claims.py", "scripts/apply_audit.py", "scripts/resolve_backfill.py", "scripts/refresh_summaries.py",
         ".github/workflows/daily.yml", "site/app.js",
         "site/index.html"]

PROMPT = """You are reviewing LeakWatch: a site that extracts AI-lab "leak claims" from X posts, grades them against what
actually happened (LLM + web search), scores leakers (Bayesian credibility, impact, Leak score) and shows a feed +
leaderboard. A daily GitHub Action runs leakwatch/daily.py then scripts/build_site.py and deploys site/ to Pages.

Find REAL problems, prioritised: correctness bugs, logic errors in scoring/no-hindsight legitimacy, prompt/LLM-pipeline
weaknesses that would produce wrong verdicts, data-integrity risks in the daily run (races, dedupe, id collisions,
state growth), cost/rate-limit risks, front-end bugs or misleading displays, security issues. For each: file + function,
what goes wrong (concrete scenario), and the fix. Skip style nits. Be specific and skeptical; say so if something you
flag might be intended. {focus}"""


def main():
    focus = " ".join(sys.argv[1:])
    code = "\n\n".join(f"===== {f} =====\n{(ROOT / f).read_text(encoding='utf-8')}" for f in FILES)
    body = {"model": "gpt-6-astra", "instructions": PROMPT.format(focus=("FOCUS: " + focus) if focus else ""),
            "input": code, "reasoning": {"effort": "high"}}
    t = time.time()
    r = requests.post("https://api.openai.com/v1/responses", json=body, timeout=1800,
                      headers={"Authorization": f"Bearer {OPENAI_KEY}"})
    r.raise_for_status()
    d = r.json()
    _log_spend("gpt-6-astra", d.get("usage") or {}, 0)
    text = "".join(c.get("text", "") for o in d.get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []))
    out = ROOT / "data" / "cache" / f"astra_review_{int(t)}.md"
    out.write_text(text, encoding="utf-8")
    print(f"{out} ({round(time.time() - t)}s, usage {d.get('usage', {}).get('input_tokens')} in / "
          f"{d.get('usage', {}).get('output_tokens')} out)")


if __name__ == "__main__":
    main()
