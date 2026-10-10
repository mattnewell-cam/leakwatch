"""Minimal OpenAI Responses API wrapper returning schema-validated JSON."""
import json
import time

import requests

from .common import OPENAI_KEY

URL = "https://api.openai.com/v1/responses"
USAGE = {"input": 0, "cached": 0, "output": 0, "searches": 0, "calls": 0}


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
    for attempt in range(5):
        try:
            r = requests.post(URL, json=body, timeout=timeout,
                              headers={"Authorization": f"Bearer {OPENAI_KEY}"})
            if r.status_code in (429, 500, 502, 503, 504):
                last = r.text[:300]
                time.sleep(3 + attempt * 5)
                continue
            r.raise_for_status()
            d = r.json()
            u = d.get("usage") or {}
            USAGE["calls"] += 1
            USAGE["input"] += u.get("input_tokens", 0)
            USAGE["cached"] += (u.get("input_tokens_details") or {}).get("cached_tokens", 0)
            USAGE["output"] += u.get("output_tokens", 0)
            USAGE["searches"] += sum(1 for o in d.get("output", []) if o.get("type") == "web_search_call")
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
