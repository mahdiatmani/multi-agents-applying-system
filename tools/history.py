import os
import json
import threading

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "history.json")
history_lock = threading.Lock()

_cache: dict | None = None


def _empty() -> dict:
    return {"jobs": [], "people": [], "posts": []}


def _read_disk() -> dict:
    if not os.path.exists(HISTORY_FILE):
        return _empty()
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _empty()
    for key in ("jobs", "people", "posts"):
        data.setdefault(key, [])
    return data


def _ensure_loaded() -> dict:
    global _cache
    if _cache is None:
        _cache = _read_disk()
        for key, items in list(_cache.items()):
            _cache[key] = set(items) if isinstance(items, list) else set()
    return _cache


def _flush_disk(snapshot: dict) -> None:
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    serializable = {k: sorted(v) for k, v in snapshot.items()}
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2)


def is_processed(category: str, identifier: str) -> bool:
    if not identifier:
        return False
    with history_lock:
        cache = _ensure_loaded()
        return identifier in cache.get(category, set())


def mark_processed(category: str, identifier: str) -> None:
    if not identifier:
        return
    with history_lock:
        cache = _ensure_loaded()
        bucket = cache.setdefault(category, set())
        if identifier in bucket:
            return
        bucket.add(identifier)
        _flush_disk(cache)


def reset_history() -> None:
    global _cache
    with history_lock:
        _cache = {"jobs": set(), "people": set(), "posts": set()}
        _flush_disk(_cache)
