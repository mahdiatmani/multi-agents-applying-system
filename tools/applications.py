import os
import json
import threading
from datetime import date

APPLICATIONS_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "applications.json")
LOCK = threading.Lock()
DEFAULT_DAILY_CAP = int(os.getenv("MAX_APPLICATIONS_PER_DAY", "50"))


def _empty() -> dict:
    return {"daily_counts": {}}


def _load() -> dict:
    if not os.path.exists(APPLICATIONS_FILE):
        return _empty()
    try:
        with open(APPLICATIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("daily_counts", {})
        return data
    except Exception:
        return _empty()


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(APPLICATIONS_FILE), exist_ok=True)
    tmp = APPLICATIONS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, APPLICATIONS_FILE)


def today_count() -> int:
    with LOCK:
        return _load()["daily_counts"].get(str(date.today()), 0)


def can_apply_today(cap: int = DEFAULT_DAILY_CAP) -> bool:
    return today_count() < cap


def record_application() -> int:
    """Increment today's application counter. Returns the new total for today."""
    with LOCK:
        data = _load()
        today = str(date.today())
        data["daily_counts"][today] = data["daily_counts"].get(today, 0) + 1
        _save(data)
        return data["daily_counts"][today]


def stats() -> dict:
    with LOCK:
        data = _load()
        return {
            "today_count": data["daily_counts"].get(str(date.today()), 0),
            "daily_cap": DEFAULT_DAILY_CAP,
        }


def reset() -> None:
    with LOCK:
        _save(_empty())
