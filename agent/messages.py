"""Typed message protocol for inter-agent / inter-model communication.

Every hop between the orchestrator (GPT-OSS) and a sub-agent (e.g. the Qwen3
CodeAgent) is a structured `AgentMessage`, not free text — keeping multi-model
flows debuggable and consistent with the structured-output discipline already
used throughout `agent/nodes.py`.

Payloads are themselves typed: `Plan` / `Step` (planner output), `CodeSpec`
(request to the CodeAgent), `ToolHandle` (a hot-loaded skill), `ToolResult`
(outcome of any tool call).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from tools.model_router import TaskKind


def new_trace_id() -> str:
    """One run produces many messages; this correlates them in the audit log."""
    return uuid.uuid4().hex[:12]


# ── Planner output ────────────────────────────────────────────────────────────
class Step(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool: str = Field(..., description="Registered tool name to invoke.")
    args: dict[str, Any] = Field(default_factory=dict)
    task_kind: TaskKind = Field(default=TaskKind.ORCHESTRATE)
    rationale: str = Field(default="", description="Why this step, one sentence.")


class Plan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    goal: str = Field(..., description="The objective this plan serves.")
    steps: list[Step] = Field(default_factory=list)
    notes: str = Field(default="")


# ── CodeAgent request / response ──────────────────────────────────────────────
class CodeSpec(BaseModel):
    """A request handed to the Qwen3 CodeAgent to generate or repair a tool.

    The CodeAgent must emit a single module exposing ONE function whose name +
    signature match `function_name` / `signature`. `context` carries whatever
    grounding the orchestrator captured (a DOM probe dump, a stack trace, sample
    inputs); `acceptance_test` is Python asserted against the function in a
    sandbox before the skill is ever hot-loaded."""

    model_config = ConfigDict(extra="ignore")

    goal: str = Field(..., description="Plain-language description of the needed code.")
    function_name: str = Field(..., description="The single public function to expose.")
    signature: str = Field(..., description="e.g. 'scrape_feed_via_js(page) -> list[dict]'.")
    task_kind: TaskKind = Field(default=TaskKind.CODE_GEN)
    context: str = Field(default="", description="DOM sample / stack trace / examples.")
    acceptance_test: str = Field(
        default="",
        description=(
            "Python snippet that imports the function as `fn` and asserts on it. "
            "Run in the sandbox against a fixture before promotion."
        ),
    )
    failure_signature: str = Field(
        default="",
        description="Stable key for skill recall (e.g. 'feed_zero_posts|fp=ab12').",
    )
    allowed_imports: list[str] = Field(
        default_factory=list,
        description="Extra modules the generated code may import beyond the base allowlist.",
    )


class ToolHandle(BaseModel):
    """A skill the CodeAgent produced + hot-loaded, ready for the registry."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Registry name the skill is loaded under.")
    module_path: str = Field(..., description="Path of the generated .py file.")
    function_name: str
    signature: str
    failure_signature: str = Field(default="")
    approved: bool = Field(default=True, description="False while awaiting human review.")
    source_excerpt: str = Field(default="", description="First lines, for the audit log.")


# ── Generic tool outcome ──────────────────────────────────────────────────────
class ToolResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool: str
    ok: bool
    value: Any = None
    error: str = Field(default="")
    observation: str = Field(
        default="",
        description="Short natural-language summary fed back into the orchestrator's scratchpad.",
    )


# ── The envelope ──────────────────────────────────────────────────────────────
AgentName = Literal["orchestrator", "code_agent", "evaluator", "memory", "executor"]
Intent = Literal["request", "result", "error", "handoff"]


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sender: AgentName
    recipient: AgentName
    intent: Intent
    task_kind: TaskKind
    trace_id: str = Field(default_factory=new_trace_id)
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str = Field(default="", description="Human-readable one-liner for the live log.")

    def log_line(self) -> str:
        arrow = {"request": "→", "result": "✓", "error": "✗", "handoff": "⇢"}.get(self.intent, "·")
        return f"[{self.trace_id}] {self.sender} {arrow} {self.recipient} ({self.task_kind.value}): {self.summary}"


def message(
    sender: AgentName,
    recipient: AgentName,
    intent: Intent,
    task_kind: TaskKind,
    *,
    payload: Optional[dict[str, Any]] = None,
    summary: str = "",
    trace_id: Optional[str] = None,
) -> AgentMessage:
    """Convenience constructor that threads an existing trace_id when given."""
    kwargs: dict[str, Any] = {
        "sender": sender,
        "recipient": recipient,
        "intent": intent,
        "task_kind": task_kind,
        "payload": payload or {},
        "summary": summary,
    }
    if trace_id:
        kwargs["trace_id"] = trace_id
    return AgentMessage(**kwargs)
