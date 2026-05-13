import os
import json
import tempfile
import threading

OVERRIDES_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "state", "profile_overrides.json"))
_lock = threading.Lock()

FIELDS = (
    "first_name", "last_name", "email", "phone", "city",
    "linkedin", "github", "portfolio", "years_exp",
    "authorized", "sponsorship", "relocate", "notice", "salary",
)


def _read() -> dict:
    if not os.path.exists(OVERRIDES_FILE):
        return {}
    try:
        with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write(data: dict) -> None:
    os.makedirs(os.path.dirname(OVERRIDES_FILE), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".overrides-", suffix=".tmp", dir=os.path.dirname(OVERRIDES_FILE))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, OVERRIDES_FILE)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def load() -> dict:
    with _lock:
        return _read()


def save(overrides: dict) -> dict:
    clean = {}
    for k in FIELDS:
        v = overrides.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            clean[k] = s
    with _lock:
        _write(clean)
    return clean


def get(field: str) -> str:
    return str(load().get(field) or "")
