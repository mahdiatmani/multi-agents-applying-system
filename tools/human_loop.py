"""Human-in-the-loop question queue.

When the layered form-fill resolver can't answer a required field, a worker thread can
call `ask_user()` which blocks on a threading.Event until the FastAPI side calls
`submit_answer()` from a /api/answer-question handler.

The web server sets a notifier (`set_notifier`) at startup so each new question is pushed
onto the SSE feed as `{action: "ASK_HUMAN", ...}`. The frontend opens a modal in response."""

import threading
import uuid
from typing import Callable, Iterable, Optional

_LOCK = threading.Lock()
_QUESTIONS: dict[str, dict] = {}
_NOTIFY: Optional[Callable[[dict], None]] = None


def set_notifier(callback: Callable[[dict], None]) -> None:
    """Server sets a callback used to push SSE events when a question is opened/closed."""
    global _NOTIFY
    _NOTIFY = callback


def _notify(payload: dict) -> None:
    cb = _NOTIFY
    if not cb:
        return
    try:
        cb(payload)
    except Exception:
        pass


def ask_user(
    label: str,
    options: Iterable[str] | None,
    kind: str,
    context_msg: str = "",
    timeout: float = 600.0,
) -> Optional[str]:
    """Block the calling worker thread until the user answers (or times out / is cancelled).

    Returns the user's answer string on success, None on timeout / cancel / empty submit /
    if a stop was requested (so cascading ask_user calls during shutdown unwind fast)."""
    # Stop short-circuit: don't enqueue new questions during shutdown.
    try:
        from tools import run_control
        if run_control.is_stopping():
            return None
    except Exception:
        pass
    qid = uuid.uuid4().hex[:12]
    ev = threading.Event()
    entry = {
        "id": qid,
        "label": label,
        "options": [str(o) for o in (options or []) if str(o).strip()],
        "kind": kind,
        "context": context_msg,
        "event": ev,
        "answer": None,
        "save_for_future": True,
        "cancelled": False,
    }
    with _LOCK:
        _QUESTIONS[qid] = entry

    payload = {
        "action": "ASK_HUMAN",
        "type": "warning",
        "message": f"✋ Need your input: {label}",
        "question": {
            "id": qid,
            "label": label,
            "options": entry["options"],
            "kind": kind,
            "context": context_msg,
        },
    }
    _notify(payload)
    print(f"[Human] Waiting on user for: label={label!r} kind={kind} options={entry['options']}", flush=True)

    answered = ev.wait(timeout=timeout)
    with _LOCK:
        final = _QUESTIONS.pop(qid, None)

    if not answered:
        print(f"[Human] Question {qid} timed out after {timeout}s for {label!r}", flush=True)
        _notify({
            "action": "ANSWER_HUMAN",
            "type": "info",
            "message": f"Question dismissed (timeout): {label}",
            "question_id": qid,
        })
        return None
    if final is None or final.get("cancelled"):
        _notify({
            "action": "ANSWER_HUMAN",
            "type": "info",
            "message": f"Question cancelled: {label}",
            "question_id": qid,
        })
        return None

    answer = (final.get("answer") or "").strip()
    if not answer:
        _notify({
            "action": "ANSWER_HUMAN",
            "type": "info",
            "message": f"Skipped: {label}",
            "question_id": qid,
        })
        return None

    print(f"[Human] User answered {qid}: {answer!r}", flush=True)
    if final.get("save_for_future"):
        try:
            _save_to_qa_overrides(label, answer)
        except Exception as exc:
            print(f"[Human] failed to persist override: {exc}", flush=True)

    _notify({
        "action": "ANSWER_HUMAN",
        "type": "success",
        "message": f"Got your input for {label!r}.",
        "question_id": qid,
    })
    return answer


def list_pending() -> list[dict]:
    with _LOCK:
        return [
            {
                "id": qid,
                "label": q["label"],
                "options": q["options"],
                "kind": q["kind"],
                "context": q["context"],
            }
            for qid, q in _QUESTIONS.items()
        ]


def submit_answer(qid: str, answer: Optional[str], save_for_future: bool = False) -> bool:
    with _LOCK:
        q = _QUESTIONS.get(qid)
        if not q:
            return False
        q["answer"] = answer if answer is not None else ""
        q["save_for_future"] = bool(save_for_future)
        ev = q["event"]
    ev.set()
    return True


def cancel(qid: str) -> bool:
    with _LOCK:
        q = _QUESTIONS.get(qid)
        if not q:
            return False
        q["cancelled"] = True
        q["answer"] = None
        ev = q["event"]
    ev.set()
    return True


def cancel_all() -> int:
    """Release every waiting thread with a cancel signal. Returns the number cancelled."""
    with _LOCK:
        items = list(_QUESTIONS.values())
    for q in items:
        q["cancelled"] = True
        q["answer"] = None
        try:
            q["event"].set()
        except Exception:
            pass
    return len(items)


def _save_to_qa_overrides(label: str, answer: str) -> None:
    """Persist this answer so the same field auto-fills next time without asking."""
    import re
    from tools import qa_overrides

    label = (label or "").strip()
    if not label:
        return
    # Build a tolerant regex from the label: escape and anchor loosely.
    pattern = re.escape(label[:120])
    entries = qa_overrides.load_entries()
    # Avoid duplicate entries with the same pattern.
    for e in entries:
        if e.get("pattern") == pattern:
            e["answer"] = answer
            qa_overrides.save_entries(entries)
            print(f"[Human] Updated qa_overrides for {label!r} → {answer!r}", flush=True)
            return
    entries.append({"pattern": pattern, "answer": answer})
    qa_overrides.save_entries(entries)
    print(f"[Human] Saved qa_overrides {label!r} → {answer!r}", flush=True)
