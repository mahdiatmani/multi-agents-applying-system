"""Apply-via-link tracker: hiring posts that say 'apply at <url>' or contain an
external ATS link the bot doesn't auto-click. The user reviews each entry and
applies manually."""

import os
import json
import threading
from datetime import datetime

LINKS_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "apply_link_posts.json")
_LOCK = threading.Lock()

VALID_STATUSES = {"new", "opened", "applied", "dismissed"}


def _empty() -> dict:
    return {"items": []}


def _load() -> dict:
    if not os.path.exists(LINKS_FILE):
        return _empty()
    try:
        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("items", [])
        return data
    except Exception:
        return _empty()


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(LINKS_FILE), exist_ok=True)
    tmp = LINKS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, LINKS_FILE)


def record_link(
    apply_url: str,
    post_author: str = "",
    post_url: str = "",
    post_excerpt: str = "",
    match_score: int | None = None,
) -> bool:
    """Dedupes on apply_url + post_url."""
    if not apply_url:
        return False
    with _LOCK:
        data = _load()
        for it in data["items"]:
            if it.get("apply_url") == apply_url and it.get("post_url") == post_url:
                return False
        data["items"].append({
            "apply_url": apply_url,
            "post_author": post_author or "",
            "post_url": post_url or "",
            "post_excerpt": post_excerpt or "",
            "match_score": match_score,
            "captured_at": datetime.now().isoformat(),
            "status": "new",
        })
        _save(data)
        return True


def list_items(status: str | None = None) -> list[dict]:
    with _LOCK:
        items = _load()["items"]
    if status is None:
        return list(reversed(items))
    return [it for it in reversed(items) if it.get("status") == status]


def set_status(identifier: str, status: str) -> bool:
    if status not in VALID_STATUSES:
        return False
    with _LOCK:
        data = _load()
        found = False
        for it in data["items"]:
            if it.get("apply_url") == identifier or it.get("post_url") == identifier:
                it["status"] = status
                found = True
        if found:
            _save(data)
        return found


def remove(identifier: str) -> bool:
    with _LOCK:
        data = _load()
        before = len(data["items"])
        data["items"] = [
            it for it in data["items"]
            if it.get("apply_url") != identifier and it.get("post_url") != identifier
        ]
        if len(data["items"]) == before:
            return False
        _save(data)
        return True


def reset() -> None:
    with _LOCK:
        _save(_empty())


def stats() -> dict:
    with _LOCK:
        items = _load()["items"]
    return {
        "total": len(items),
        "new": sum(1 for it in items if it.get("status") == "new"),
        "opened": sum(1 for it in items if it.get("status") == "opened"),
        "applied": sum(1 for it in items if it.get("status") == "applied"),
        "dismissed": sum(1 for it in items if it.get("status") == "dismissed"),
    }
