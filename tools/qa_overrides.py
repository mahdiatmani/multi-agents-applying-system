import os
import re
import json
import threading
from typing import Iterable

QA_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "qa_overrides.json")
LOCK = threading.Lock()

_DEFAULTS = [
    {"pattern": r"start immediately|can you start|when can you start|notice period|available to start", "answer": "Yes"},
    {"pattern": r"are you (legally )?authori[sz]ed|right to work|work authori[sz]ation", "answer": "Yes"},
    {"pattern": r"require (visa )?sponsorship|need sponsorship|visa sponsorship", "answer": "No"},
    {"pattern": r"willing to relocate|able to relocate|open to relocation", "answer": "Yes"},
    {"pattern": r"willing to travel|travel \d+%", "answer": "Yes"},
    {"pattern": r"do you have a (valid )?driver'?s? licen[sc]e", "answer": "Yes"},
    {"pattern": r"are you (currently )?employed", "answer": "No"},
    {"pattern": r"convicted|criminal record|felony", "answer": "No"},
    {"pattern": r"(expected )?salary|salary expectation|compensation", "answer": "Negotiable"},
]


def _empty() -> dict:
    return {"entries": list(_DEFAULTS)}


def _load() -> dict:
    if not os.path.exists(QA_FILE):
        return _empty()
    try:
        with open(QA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            return _empty()
        return data
    except Exception:
        return _empty()


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(QA_FILE), exist_ok=True)
    tmp = QA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, QA_FILE)


def load_entries() -> list[dict]:
    with LOCK:
        return list(_load().get("entries", []))


def save_entries(entries: list[dict]) -> None:
    cleaned: list[dict] = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        pat = str(e.get("pattern", "")).strip()
        ans = str(e.get("answer", "")).strip()
        if not pat or not ans:
            continue
        # Validate regex; skip silently if invalid.
        try:
            re.compile(pat, re.IGNORECASE)
        except re.error:
            continue
        cleaned.append({"pattern": pat, "answer": ans})
    with LOCK:
        _save({"entries": cleaned})


def reset_to_defaults() -> None:
    with LOCK:
        _save(_empty())


def match(label: str, options: Iterable[str] | None = None) -> str | None:
    """Return the answer for the first regex that matches the label, scoped to options if provided."""
    if not label:
        return None
    text = label.strip()
    if not text:
        return None
    opt_list = [str(o).strip() for o in (options or []) if str(o).strip()]
    for entry in load_entries():
        try:
            if re.search(entry["pattern"], text, re.IGNORECASE):
                answer = entry["answer"]
                # If options are constrained, pick the option that contains the answer (case-insensitive).
                if opt_list:
                    al = answer.lower()
                    for opt in opt_list:
                        if al in opt.lower() or opt.lower().startswith(al):
                            return opt
                    # Answer doesn't fit any option — fall through to other layers.
                    continue
                return answer
        except re.error:
            continue
    return None
