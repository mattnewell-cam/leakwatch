"""Minimal OpenAI Responses API wrapper returning schema-validated JSON."""
import json
import random
import re
import time

import requests

from .common import OPENAI_KEY

URL = "https://api.openai.com/v1/responses"
USAGE = {"input": 0, "cached": 0, "output": 0, "searches": 0, "calls": 0}
# $ per 1M tokens: (input, cached input, output). Third-party-reported prices; search assumed $10/1k calls.
PRICES = {"gpt-6-luna": (0.10, 0.01, 0.50), "gpt-5.4": (2.50, 0.25, 15.0), "gpt-5.4-mini": (0.75, 0.075, 4.5),
          "gpt-6-astra": (10.0, 1.0, 50.0), "gpt-6-sol": (2.0, 0.2, 10.0)}
SEARCH_PRICE = 0.01


def _log_spend(model, u, searches):
    """Append estimated cost of each call to a local ledger (data/cache/spend.jsonl)."""
    try:
        from .common import DATA
        pi, pc, po = PRICES.get(model, (2.5, 0.25, 15.0))
        inp = u.get("input_tokens", 0)
        cached = (u.get("input_tokens_details") or {}).get("cached_tokens", 0)
        cost = ((inp - cached) * pi + cached * pc + u.get("output_tokens", 0) * po) / 1e6 + searches * SEARCH_PRICE
        (DATA / "cache").mkdir(parents=True, exist_ok=True)
        with open(DATA / "cache" / "spend.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "model": model, "cost": round(cost, 5)}) + "\n")
    except Exception:
        pass


def call_json(model, system, user, schema, name="out", web_search=False, reasoning=None, timeout=300, max_tool_calls=None):
    body = {
        "model": model,
        "instructions": system,
        "input": user,
        "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
    }
    if web_search:
        body["tools"] = [{"type": "web_search"}]
    if reasoning:
        body["reasoning"] = {"effort": reasoning}
    if max_tool_calls:
        body["max_tool_calls"] = max_tool_calls
    last = None
    deadline = time.time() + max(timeout * 2, 900)     # overall cap so one call can't eat the whole job
    for attempt in range(12):
        if time.time() > deadline:
            break
        try:
            r = requests.post(URL, json=body, timeout=timeout,
                              headers={"Authorization": f"Bearer {OPENAI_KEY}"})
            if r.status_code in (429, 500, 502, 503, 504):
                last = r.text[:300]
                if r.status_code == 429 and "insufficient_quota" in r.text:
                    break                                 # out of credit: retrying won't help
                m = re.search(r"try again in ([\d.]+)(ms|s)", r.text)
                wait = (float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)) if m else 3 + attempt * 5
                time.sleep(min(60, wait + 1 + random.random() * 3))
                continue
            if 400 <= r.status_code < 500:
                # permanent (bad key, unknown model, invalid schema, too large) - don't retry
                raise RuntimeError(f"LLM call rejected ({r.status_code}): {r.text[:300]}")
            r.raise_for_status()
            d = r.json()
            u = d.get("usage") or {}
            USAGE["calls"] += 1
            USAGE["input"] += u.get("input_tokens", 0)
            USAGE["cached"] += (u.get("input_tokens_details") or {}).get("cached_tokens", 0)
            USAGE["output"] += u.get("output_tokens", 0)
            ns = sum(1 for o in d.get("output", []) if o.get("type") == "web_search_call")
            USAGE["searches"] += ns
            _log_spend(model, u, ns)
            for o in d.get("output", []):
                if o.get("type") == "message":
                    for c in o.get("content", []):
                        if c.get("type") == "output_text":
                            return json.loads(c["text"])
            last = "no message in output"
        except (requests.RequestException, json.JSONDecodeError) as e:
            last = str(e)[:300]
            time.sleep(3 + attempt * 5)
    raise RuntimeError(f"LLM call failed: {last}")


def obj(props, required=None):
    """Strict-mode object schema helper: every property required, no extras."""
    return {"type": "object", "additionalProperties": False, "properties": props,
            "required": required or list(props)}


def arr(items):
    return {"type": "array", "items": items}


S = {"type": "string"}
I = {"type": "integer"}
N = {"type": "number"}
B = {"type": "boolean"}


def enum(*vals):
    return {"type": "string", "enum": list(vals)}
