"""Skill memory — the learning loop that makes self-healing cheap over time.

When the CodeAgent generates a tool to fix a failure, we persist a *skill* keyed
by the failure signature. Next time the same failure recurs, `recall()` returns
the already-generated, already-validated skill and the orchestrator re-loads it
instead of paying for a fresh codegen round-trip.

Storage piggybacks on the existing `state/self_heal/` directory (which already
holds incident memory + markdown audit snapshots). Skills live in
`state/self_heal/skills.json`; the generated code itself lives in
`tools/generated/`.

This is deliberately a flat keyed store, not a vector DB — failure signatures are
exact-match keys (DOM fingerprints, incident kinds). An embedding-based fuzzy
recall can layer on later behind the same `recall()` interface.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Optional

from agent.messages import ToolHandle

_HERE = os.path.dirname(__file__)
_SELF_HEAL_DIR = os.path.normpath(os.path.join(_HERE, "..", "state", "self_heal"))
_SKILLS_PATH = os.path.join(_SELF_HEAL_DIR, "skills.json")

_lock = threading.Lock()


def _ensure_dir() -> None:
    os.makedirs(_SELF_HEAL_DIR, exist_ok=True)


def _load() -> dict:
    try:
        with open(_SKILLS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {"skills": {}}
    except (FileNotFoundError, json.JSONDecodeError):
        return {"skills": {}}


def _save(data: dict) -> None:
    _ensure_dir()
    tmp = _SKILLS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, _SKILLS_PATH)


def remember(handle: ToolHandle, *, summary: str = "") -> None:
    """Persist a generated skill keyed by its failure signature.

    No-op when the skill has no failure_signature (one-off scripts that aren't
    worth recalling)."""
    key = (handle.failure_signature or "").strip()
    if not key:
        return
    with _lock:
        data = _load()
        skills = data.setdefault("skills", {})
        record = skills.get(key, {})
        record.update(
            {
                "name": handle.name,
                "module_path": handle.module_path,
                "function_name": handle.function_name,
                "signature": handle.signature,
                "failure_signature": key,
                "approved": handle.approved,
                "summary": summary or record.get("summary", ""),
                "hits": int(record.get("hits", 0)),
                "created": record.get("created") or datetime.now().isoformat(),
                "updated": datetime.now().isoformat(),
            }
        )
        skills[key] = record
        _save(data)


def recall(failure_signature: str) -> Optional[ToolHandle]:
    """Return a previously generated skill for this failure, if one exists AND its
    generated module is still on disk. Bumps a hit counter so we can see which
    skills earn their keep. Returns None on miss."""
    key = (failure_signature or "").strip()
    if not key:
        return None
    with _lock:
        data = _load()
        record = data.get("skills", {}).get(key)
        if not record:
            return None
        module_path = record.get("module_path") or ""
        if module_path and not os.path.exists(module_path):
            # Skill was recorded but the generated file is gone — treat as a miss
            # so the CodeAgent regenerates it.
            return None
        record["hits"] = int(record.get("hits", 0)) + 1
        record["last_hit"] = datetime.now().isoformat()
        data["skills"][key] = record
        _save(data)
        return ToolHandle(
            name=record.get("name", ""),
            module_path=module_path,
            function_name=record.get("function_name", ""),
            signature=record.get("signature", ""),
            failure_signature=key,
            approved=bool(record.get("approved", True)),
        )


def list_skills() -> list[dict]:
    """All known skills, for the dashboard / audit."""
    return list(_load().get("skills", {}).values())


def forget(failure_signature: str) -> bool:
    """Drop a skill (e.g. it regressed). Returns True if something was removed."""
    key = (failure_signature or "").strip()
    with _lock:
        data = _load()
        if key in data.get("skills", {}):
            del data["skills"][key]
            _save(data)
            return True
    return False
