"""Apply Claude audit results (data/cache/audit/out_*.json) to data/claims.json and data/profiles.json."""
import glob
import json
import os
from datetime import datetime, timezone

from leakwatch.common import DATA, load_json, now_iso, save_json

VALID = {"true", "mostly_true", "partly_true", "false", "pending", "already_public", "unverifiable"}


def main():
    claims = load_json(DATA / "claims.json")
    byid = {c["id"]: c for c in claims}
    profiles = load_json(DATA / "profiles.json", {})
    changed = checked = 0
    stale = 0
    for f in sorted(glob.glob(str(DATA / "cache" / "audit" / "out_*.json"))):
        audit_time = datetime.fromtimestamp(os.path.getmtime(f), timezone.utc).isoformat()
        try:
            out = json.load(open(f, encoding="utf-8"))
        except Exception as e:
            print("bad audit file", f, e)
            continue
        for a in out.get("claims", []):
            c = byid.get(a.get("id"))
            if not c or not c.get("resolution"):
                continue
            r = c["resolution"]
            # never let an old audit overwrite a verdict that was re-graded after the audit was written
            if not r.get("vetted") and (r.get("resolved_at") or "") > audit_time:
                stale += 1
                continue
            v = a.get("verdict")
            if v not in VALID:
                continue
            checked += 1
            prev = r.get("vetted", {}).get("changed_from") or r["verdict"]
            note = (a.get("note") or "").strip()
            vet = {"by": "claude-audit", "at": now_iso(), "note": note}
            if v != r["verdict"] or (a.get("public_date") and a.get("public_date") != r.get("public_date")):
                if v != r["verdict"]:
                    vet["changed_from"] = prev
                    changed += 1
                r["verdict"] = v
                if a.get("public_date"):
                    r["public_date"] = a["public_date"]
                if note:
                    r["explanation"] = note if len(note) > 40 else r.get("explanation", "")
            r["vetted"] = vet
        for h, s in (out.get("summaries") or {}).items():
            profiles[h.lower().lstrip("@")] = {"summary": s}
    save_json(DATA / "claims.json", claims)
    save_json(DATA / "profiles.json", profiles)
    print(f"audited {checked} claims, changed {changed}; skipped {stale} re-graded since; {len(profiles)} summaries")


if __name__ == "__main__":
    main()
