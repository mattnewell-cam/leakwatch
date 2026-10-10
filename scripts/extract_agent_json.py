"""Pull the last ```json array out of a subagent transcript (jsonl)."""
import json, re, sys
from pathlib import Path
SUB = Path.home() / ".claude/projects"
def final_text(agent_id):
    f = Path(__file__).resolve().parent.parent / "data/cache/agents" / f"{agent_id}.jsonl"
    last = ""
    for line in f.read_text(encoding="utf-8").splitlines():
        try: d = json.loads(line)
        except Exception: continue
        m = d.get("message") or {}
        if m.get("role") == "assistant":
            c = m.get("content")
            if isinstance(c, list):
                t = "".join(x.get("text", "") for x in c if x.get("type") == "text")
            else: t = c or ""
            if t.strip(): last = t
    return last
def extract(agent_id):
    t = final_text(agent_id)
    blocks = re.findall(r"```json\s*(.*?)```", t, re.S)
    for b in reversed(blocks):
        try: return json.loads(b)
        except Exception: pass
    i = t.find("["); j = t.rfind("]")
    return json.loads(t[i:j+1])
if __name__ == "__main__":
    out = []
    for a in sys.argv[2:]: 
        x = extract(a); print(a, len(x), file=sys.stderr); out += x
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
