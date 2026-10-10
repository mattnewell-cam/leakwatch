"""Shared config, paths and JSON helpers."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("LEAKWATCH_DATA") or ROOT / "data")
RAW = DATA / "raw"
SITE = ROOT / "site"


def _load_local_env():
    """Local runs read keys from ~/.leakwatch.env; CI uses repo secrets."""
    p = Path.home() / ".leakwatch.env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_local_env()

TWITTER_KEY = os.environ.get("TWITTERAPI_IO_KEY", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")

# Cheap model for bulk filtering/extraction; stronger one for judging + resolution.
MODEL_FAST = os.environ.get("LEAKWATCH_MODEL_FAST", "gpt-5.4-mini")
MODEL_SMART = os.environ.get("LEAKWATCH_MODEL_SMART", "gpt-5.4")


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, obj, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(path)
