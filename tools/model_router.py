"""Two-role model layer + task router.

The system uses TWO Ollama models, selected by *role*, not hardcoded tags:

  • REASONING_MODEL  — planning, orchestration, evaluation, outreach writing,
                       classification, summarization. Default: GPT-OSS.
  • CODING_MODEL     — generating/repairing source code: selectors, scrapers,
                       form handlers, scripts, debugging. Default: Qwen3-coder.

Every unit of work declares a `TaskKind`; `model_for()` maps it to a role and
`llm_for()` hands back a ready ChatOllama (optionally tool-bound). Routing is a
plain dict lookup — deterministic and free — for the ~95% of calls whose kind is
known at the call site. `classify_kind()` is the fallback for free-form tasks the
planner emits without an obvious kind.

Both model tags are env-configurable so you can point them at local or cloud
variants without touching code:

    REASONING_MODEL=gpt-oss:120b-cloud
    CODING_MODEL=qwen3-coder:480b-cloud
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Sequence

from langchain_ollama import ChatOllama

from tools.llm_models import get_ollama_base_url


# ── Role tags (env-configurable) ──────────────────────────────────────────────
REASONING_MODEL = os.getenv("REASONING_MODEL", os.getenv("DEFAULT_LLM_MODEL", "gpt-oss:120b-cloud"))
CODING_MODEL = os.getenv("CODING_MODEL", "qwen3-coder:480b-cloud")


class TaskKind(str, Enum):
    """What kind of work a unit is — drives which model handles it."""

    # ── Non-coding → REASONING_MODEL (GPT-OSS) ──
    PLAN = "plan"
    ORCHESTRATE = "orchestrate"
    EVALUATE = "evaluate"
    WRITE_OUTREACH = "write_outreach"
    CLASSIFY = "classify"
    SUMMARIZE = "summarize"

    # ── Coding → CODING_MODEL (Qwen3-coder) ──
    CODE_GEN = "code_gen"
    SELECTOR_REPAIR = "selector_repair"
    SCRIPT = "script"
    DEBUG = "debug"
    CODE_REVIEW = "code_review"


_CODING_KINDS: frozenset[TaskKind] = frozenset(
    {
        TaskKind.CODE_GEN,
        TaskKind.SELECTOR_REPAIR,
        TaskKind.SCRIPT,
        TaskKind.DEBUG,
        TaskKind.CODE_REVIEW,
    }
)


def is_coding(kind: TaskKind) -> bool:
    return kind in _CODING_KINDS


def model_for(kind: TaskKind, override: str | None = None) -> str:
    """Resolve the model tag for a task kind.

    An explicit `override` (e.g. the user picked a model in the dashboard) always
    wins; otherwise route by role."""
    ov = (override or "").strip()
    if ov:
        return ov
    return CODING_MODEL if is_coding(kind) else REASONING_MODEL


# Cache ChatOllama clients per (model, base_url) — building one is cheap but the
# underlying httpx client is worth reusing across the hot loop.
_llm_cache: dict[tuple[str, str], ChatOllama] = {}


def _client(model: str, temperature: float) -> ChatOllama:
    base_url = get_ollama_base_url()
    key = (f"{model}@@{temperature}", base_url)
    cached = _llm_cache.get(key)
    if cached is None:
        cached = ChatOllama(model=model, temperature=temperature, base_url=base_url)
        _llm_cache[key] = cached
    return cached


def llm_for(
    kind: TaskKind,
    *,
    temperature: float = 0,
    tools: Sequence[Any] | None = None,
    override: str | None = None,
) -> ChatOllama:
    """Return a ChatOllama bound to the right model for `kind`.

    Pass `tools` to get a tool-calling-bound client (used by the orchestrator's
    act node). `override` forwards an explicit user-chosen model."""
    model = model_for(kind, override)
    llm = _client(model, temperature)
    return llm.bind_tools(tools) if tools else llm


# ── Lightweight task classifier ───────────────────────────────────────────────
# Heuristic first (free); fall back to a tiny GPT-OSS call only when ambiguous.
_CODE_SIGNALS: tuple[str, ...] = (
    "selector", "scrape", "scraper", "xpath", "css", "regex", "parse the dom",
    "write a function", "write code", "script", "stack trace", "stacktrace",
    "traceback", "exception", ".py", "def ", "import ", "playwright", "locator",
    "json schema", "parser", "debug", "refactor",
)


def classify_kind(task_text: str) -> TaskKind:
    """Best-effort kind for a free-form task string. Heuristic match on coding
    signals; defaults to ORCHESTRATE (non-coding) when nothing fires.

    Kept deliberately cheap and dependency-free — the planner usually routes to
    the `code_agent` tool explicitly, so this is only a safety net."""
    low = (task_text or "").lower()
    if any(sig in low for sig in _CODE_SIGNALS):
        return TaskKind.CODE_GEN
    return TaskKind.ORCHESTRATE


def describe_routing() -> dict[str, str]:
    """Snapshot of the active role→tag mapping, for logs / the dashboard."""
    return {
        "reasoning_model": REASONING_MODEL,
        "coding_model": CODING_MODEL,
        "base_url": get_ollama_base_url(),
    }
