import os
import json
import threading
from datetime import datetime, date

PENDING_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "pending_connections.json")
LOCK = threading.Lock()
DEFAULT_DAILY_CAP = int(os.getenv("MAX_CONNECTIONS_PER_DAY", "30"))

VALID_STATUSES = {"pending", "accepted", "dm_sent", "declined", "dm_failed"}


def _empty() -> dict:
    return {"items": [], "daily_counts": {}}


def _load() -> dict:
    if not os.path.exists(PENDING_FILE):
        return _empty()
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("items", [])
        data.setdefault("daily_counts", {})
        return data
    except Exception:
        return _empty()


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(PENDING_FILE), exist_ok=True)
    tmp = PENDING_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, PENDING_FILE)


def today_count() -> int:
    with LOCK:
        return _load()["daily_counts"].get(str(date.today()), 0)


def can_send_today(cap: int = DEFAULT_DAILY_CAP) -> bool:
    return today_count() < cap


def has_pending(profile_url: str) -> bool:
    if not profile_url:
        return False
    with LOCK:
        return any(it.get("profile_url") == profile_url for it in _load()["items"])


def add_pending(profile_url: str, name: str, post_id: str, post_content: str, queued_dm: str) -> bool:
    if not profile_url:
        return False
    with LOCK:
        data = _load()
        if any(it.get("profile_url") == profile_url for it in data["items"]):
            return False
        data["items"].append({
            "profile_url": profile_url,
            "name": name,
            "post_id": post_id,
            "post_content": (post_content or "")[:2000],
            "queued_dm": queued_dm or "",
            "sent_at": datetime.now().isoformat(),
            "status": "pending",
            "last_checked_at": None,
            "accepted_at": None,
            "dm_sent_at": None,
        })
        today = str(date.today())
        data["daily_counts"][today] = data["daily_counts"].get(today, 0) + 1
        _save(data)
        return True


def list_items(status: str | None = None) -> list[dict]:
    with LOCK:
        items = _load()["items"]
        if status is None:
            return items
        return [it for it in items if it.get("status") == status]


def update_status(profile_url: str, status: str, dm_sent: bool = False, mark_accepted: bool = False) -> None:
    """`mark_accepted=True` stamps an `accepted_at` timestamp the first time we
    see a connection flip from pending → accepted. The sweeper uses this as the
    ripening anchor — DM only fires once 10 min has passed since accepted_at."""
    if status not in VALID_STATUSES:
        return
    with LOCK:
        data = _load()
        now = datetime.now().isoformat()
        for it in data["items"]:
            if it.get("profile_url") == profile_url:
                it["status"] = status
                it["last_checked_at"] = now
                if mark_accepted and not it.get("accepted_at"):
                    it["accepted_at"] = now
                if dm_sent:
                    it["dm_sent_at"] = now
        _save(data)


def stats() -> dict:
    with LOCK:
        data = _load()
        items = data["items"]
        return {
            "pending": sum(1 for it in items if it.get("status") == "pending"),
            "accepted": sum(1 for it in items if it.get("status") == "accepted"),
            "dm_sent": sum(1 for it in items if it.get("status") == "dm_sent"),
            "declined": sum(1 for it in items if it.get("status") == "declined"),
            "dm_failed": sum(1 for it in items if it.get("status") == "dm_failed"),
            "today_count": data["daily_counts"].get(str(date.today()), 0),
            "daily_cap": DEFAULT_DAILY_CAP,
        }


def reset() -> None:
    with LOCK:
        _save(_empty())


def ripened_accepted_items(min_age_seconds: int) -> list[dict]:
    """Return accepted entries whose accepted_at is at least min_age_seconds old.
    These are ready to be DM'd. Items without accepted_at (legacy entries that
    became accepted before this field existed) are treated as ripened."""
    from datetime import datetime as _dt
    now = _dt.now()
    out: list[dict] = []
    with LOCK:
        data = _load()
        for it in data["items"]:
            if it.get("status") != "accepted":
                continue
            ts = it.get("accepted_at")
            if not ts:
                out.append(it)
                continue
            try:
                ripe_age = (now - _dt.fromisoformat(ts)).total_seconds()
            except Exception:
                ripe_age = float("inf")
            if ripe_age >= min_age_seconds:
                out.append(it)
    return out
