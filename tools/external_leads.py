"""External leads: jobs that can't be Easy-Applied (external ATS redirect or modal
that never opened). Persisted so the user can apply to them manually."""

import os
import json
import threading
from datetime import datetime

LEADS_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "external_leads.json")
_LOCK = threading.Lock()

VALID_STATUSES = {"new", "viewed", "applied", "dismissed"}


def _empty() -> dict:
    return {"items": []}


def _load() -> dict:
    if not os.path.exists(LEADS_FILE):
        return _empty()
    try:
        with open(LEADS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("items", [])
        return data
    except Exception:
        return _empty()


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(LEADS_FILE), exist_ok=True)
    tmp = LEADS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, LEADS_FILE)


def add(
    title: str,
    company: str,
    url: str,
    destination_url: str = "",
    reason: str = "",
    search_url: str = "",
    job_identifier: str = "",
) -> bool:
    """Returns True if added, False if dedup hit (same job url or destination_url already stored)."""
    if not url and not destination_url and not job_identifier:
        return False
    with _LOCK:
        data = _load()
        for it in data["items"]:
            if url and it.get("url") == url:
                return False
            if destination_url and it.get("destination_url") == destination_url:
                return False
            if job_identifier and it.get("job_identifier") == job_identifier:
                return False
        data["items"].append({
            "title": title or "",
            "company": company or "",
            "url": url or "",
            "destination_url": destination_url or "",
            "reason": (reason or "")[:500],
            "search_url": search_url or "",
            "job_identifier": job_identifier or "",
            "captured_at": datetime.now().isoformat(),
            "status": "new",
        })
        _save(data)
        return True


def list_items(status: str | None = None) -> list[dict]:
    with _LOCK:
        items = _load()["items"]
        if status is None:
            return list(reversed(items))  # newest first
        return [it for it in reversed(items) if it.get("status") == status]


def set_status(identifier: str, status: str) -> bool:
    """Identifier matches job_identifier or url. Returns True if updated."""
    if status not in VALID_STATUSES:
        return False
    with _LOCK:
        data = _load()
        found = False
        for it in data["items"]:
            if it.get("job_identifier") == identifier or it.get("url") == identifier:
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
            if it.get("job_identifier") != identifier and it.get("url") != identifier
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
            "viewed": sum(1 for it in items if it.get("status") == "viewed"),
            "applied": sum(1 for it in items if it.get("status") == "applied"),
            "dismissed": sum(1 for it in items if it.get("status") == "dismissed"),
        }
