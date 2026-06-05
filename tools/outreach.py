"""Outreach tracking: every email draft the bot prepares is recorded here so
the user can see what was actually sent, to whom, and from which post. DMs are
tracked separately in tools/pending.py (they have a different lifecycle —
connection-request first, DM after acceptance)."""

import os
import json
import threading
from datetime import datetime

EMAILS_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "outreach_emails.json")
_LOCK = threading.Lock()

VALID_STATUSES = {"drafted", "gmail_failed", "gmail_unauth", "sent", "replied", "ignored"}


def _empty() -> dict:
    return {"items": []}


def _load() -> dict:
    if not os.path.exists(EMAILS_FILE):
        return _empty()
    try:
        with open(EMAILS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("items", [])
        return data
    except Exception:
        return _empty()


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(EMAILS_FILE), exist_ok=True)
    tmp = EMAILS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, EMAILS_FILE)


def record_draft(
    to_email: str,
    subject: str,
    body: str,
    post_author: str = "",
    post_url: str = "",
    post_excerpt: str = "",
    match_score: int | None = None,
    status: str = "drafted",
    error: str = "",
) -> bool:
    """Persist an email outreach decision. Dedupes on (to_email, post_url) —
    re-running the agent over the same post returns False without duplicating.
    Status reflects what actually happened with Gmail: 'drafted' (success),
    'gmail_unauth' (no token.json), 'gmail_failed' (API error). Persisting
    failures lets the user see what the bot WANTED to send even when Gmail
    auth is broken — they can copy the body and send manually."""
    if not to_email:
        return False
    with _LOCK:
        data = _load()
        for it in data["items"]:
            if it.get("to_email") == to_email and it.get("post_url") == post_url:
                return False
        data["items"].append({
            "to_email": to_email,
            "subject": subject or "",
            "body": body or "",
            "post_author": post_author or "",
            "post_url": post_url or "",
            "post_excerpt": post_excerpt or "",
            "match_score": match_score,
            "created_at": datetime.now().isoformat(),
            "status": status if status in VALID_STATUSES else "drafted",
            "error": error,
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
    """identifier matches to_email or post_url. Returns True if updated."""
    if status not in VALID_STATUSES:
        return False
    with _LOCK:
        data = _load()
        found = False
        for it in data["items"]:
            if it.get("to_email") == identifier or it.get("post_url") == identifier:
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
            if it.get("to_email") != identifier and it.get("post_url") != identifier
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
        "total":         len(items),
        "drafted":       sum(1 for it in items if it.get("status") == "drafted"),
        "gmail_unauth":  sum(1 for it in items if it.get("status") == "gmail_unauth"),
        "gmail_failed":  sum(1 for it in items if it.get("status") == "gmail_failed"),
        "sent":          sum(1 for it in items if it.get("status") == "sent"),
        "replied":       sum(1 for it in items if it.get("status") == "replied"),
        "ignored":       sum(1 for it in items if it.get("status") == "ignored"),
    }
