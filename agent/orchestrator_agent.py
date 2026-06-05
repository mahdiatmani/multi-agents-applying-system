"""Agentic orchestrator — a planner-executor loop driven by the REASONING_MODEL
(GPT-OSS) with tool-calling, replacing the fixed init→search→evaluate→action
graph when AGENTIC=true.

The LLM owns control flow: it calls tools (search, evaluate, act, and crucially
`code_agent` to repair itself), observes results, and decides what to do next.
We still compile to a LangGraph so the server streams it exactly as before, and
`run_control` pause/stop checkpoints are honored at every node boundary.

Shape:
    init ─▶ agent ⇄ tools ─▶ (loop | end)
            │
            └─ GPT-OSS bound to the goal's tool subset (tools_registry)

State threading: tools that produce an item (get_job_details, extract_profile,
scrape_feed) and evaluate_fit write their results back into the shared state, so
the model never has to echo large dicts back as args — action tools read the
current item from state. This keeps the LLM's job to *decisions*, not data
plumbing.
"""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END

from state import AgentState
from agent.graph import init_browser_node
from agent import tools_registry as registry
from tools.model_router import TaskKind, llm_for, describe_routing
from tools.run_control import checkpoint as _checkpoint

DEFAULT_MAX_ITERATIONS = int(os.getenv("AGENTIC_MAX_ITERATIONS", "60"))
WATCH_GOALS = {"POST", "PERSON"}

# Keys a tool may return that we merge back into the shared state so later tool
# calls (evaluate / action nodes) can read the "current item" without the LLM
# re-supplying it.
_STATE_MERGE_KEYS = (
    "job_details", "profile_details", "post_details", "posts_queue",
    "match_score", "reasoning", "draft_message", "draft_subject",
    "extracted_email", "apply_url", "action_taken",
)


_SYSTEM_PROMPT = """You are the orchestrator of a LinkedIn job-search agent. You pursue ONE goal by calling tools.

GOAL: {goal_desc}

HOW TO WORK:
1. Find items with the search/scrape tool, then for EACH item call `evaluate_fit` to score it and get a recommended action.
2. If evaluate_fit recommends an action (APPLY / NETWORK / DRAFT_EMAIL / DRAFT_DM / EXTERNAL_LINK), call the matching action tool. The item and the draft are already in shared state — you do NOT need to repeat them as arguments.
3. Loop: keep searching/evaluating/acting on new items.

SELF-HEALING (this is what makes you autonomous):
- If a search/scrape tool returns 0 items repeatedly, or a tool reports a broken selector / parse failure, DO NOT give up. Call `code_agent` to write or repair the needed code: give it a clear goal, the exact function_name + signature, the failure context you observed, and a short acceptance_test. Once it loads, retry.

SAFETY (never violate):
- The system never auto-sends DMs — `draft_dm` / `connect_and_queue_dm` only queue drafts for the user to send manually. That is intended; do not try to "send" anything.
- Respect that action tools may report a daily cap; if so, move on.

STOPPING:
- When there is no more useful work (no new items and nothing to repair), reply with the single word FINISH and no tool call.

Available tools: {tool_names}. Think step by step, but keep replies terse — your job is tool calls, not prose."""


def _goal_description(search_type: str) -> str:
    return {
        "JOB": "Find and Easy-Apply to relevant LinkedIn jobs.",
        "PERSON": "Find relevant LinkedIn profiles (HR/recruiters + CV-field peers) and queue connection+DM drafts.",
        "POST": "Work the LinkedIn home feed: find hiring posts and draft tailored email/DM/apply-link outreach.",
    }.get((search_type or "JOB").upper(), "Pursue the configured goal.")


def _initial_messages(state: AgentState) -> list:
    goal = (state.get("search_type") or "JOB").upper()
    specs = registry.tools_for_goal(goal)
    tool_names = ", ".join(s.name for s in specs)
    sys = _SYSTEM_PROMPT.format(goal_desc=_goal_description(goal), tool_names=tool_names)
    prefs = (
        f"Role(s): {state.get('search_role')}; Locations: {state.get('search_locations')}; "
        f"Workplace: {state.get('workplace_types')}; Company: {state.get('target_company') or 'any'}; "
        f"dry_run={state.get('dry_run', False)}."
    )
    return [SystemMessage(content=sys), HumanMessage(content=f"Begin. Preferences: {prefs}")]


def agent_node(state: AgentState) -> dict:
    """One reasoning turn: GPT-OSS picks the next tool call (or FINISHes)."""
    _checkpoint("agent")
    goal = (state.get("search_type") or "JOB").upper()
    messages = state.get("messages") or _initial_messages(state)

    llm = llm_for(
        TaskKind.ORCHESTRATE,
        tools=registry.schemas_for_goal(goal),
        override=state.get("llm_model"),
    )
    ai: AIMessage = llm.invoke(messages)
    messages = messages + [ai]

    tool_calls = getattr(ai, "tool_calls", None) or []
    iterations = int(state.get("iterations", 0)) + 1
    if tool_calls:
        return {"messages": messages, "iterations": iterations,
                "action_taken": "THINKING", "_pending_tool_calls": tool_calls}
    # No tool call → the model is done (or stalled). Treat as finish.
    return {"messages": messages, "iterations": iterations,
            "action_taken": "FINISHED", "_pending_tool_calls": []}


def tools_node(state: AgentState) -> dict:
    """Execute the pending tool calls, thread results back into state, and append
    ToolMessages so the model sees the observations on its next turn."""
    _checkpoint("tools")
    messages = list(state.get("messages") or [])
    pending = state.get("_pending_tool_calls") or []
    ctx = {"state": dict(state)}
    merged: dict[str, Any] = {}
    last_action = state.get("action_taken", "THINKING")

    for call in pending:
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
        args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
        call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", name)

        result = registry.execute(name, args or {}, ctx)

        # Merge recognized result keys into both the live ctx (for the next call
        # in this same batch) and the state update we return.
        value = result.value if isinstance(result.value, dict) else {}
        for k in _STATE_MERGE_KEYS:
            if k in value:
                merged[k] = value[k]
                ctx["state"][k] = value[k]
        if name == "evaluate_fit" and isinstance(result.value, dict):
            # evaluate_fit returns the full evaluator output dict directly.
            for k in _STATE_MERGE_KEYS:
                if k in result.value:
                    merged[k] = result.value[k]
                    ctx["state"][k] = result.value[k]
        # Surface terminal actions so the server records stats/activity.
        if value.get("action_taken") in (
            "APPLIED", "APPLY_FAILED", "DRAFTED_EMAIL", "DRAFTED_DM",
            "EXTERNAL_LEAD", "EXTERNAL_LINK_RECORDED", "NETWORKED",
        ):
            last_action = value["action_taken"]

        messages.append(ToolMessage(
            content=_truncate(result.observation or json.dumps(_jsonsafe(result.value))[:800]),
            tool_call_id=call_id or name,
            name=name,
        ))

    out = {"messages": messages, "_pending_tool_calls": []}
    out.update(merged)
    out["action_taken"] = last_action
    return out


def _truncate(text: str, limit: int = 1200) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + " …(truncated)"


def _jsonsafe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _max_iters(state: AgentState) -> int:
    return int(state.get("max_iterations") or DEFAULT_MAX_ITERATIONS)


def router(state: AgentState) -> str:
    """init→agent; agent→tools|end; tools→agent (until max iters)."""
    errors = state.get("errors", [])
    if any("Login failed" in e or "Credentials not set" in e for e in errors):
        return "end"
    if int(state.get("iterations", 0)) >= _max_iters(state):
        print(f"[Agent] Reached max iterations ({_max_iters(state)}). Ending.", flush=True)
        return "end"
    action = state.get("action_taken", "")
    if action == "FINISHED":
        return "end"
    if state.get("_pending_tool_calls"):
        return "tools"
    return "agent"


def build_agentic_agent(search_type: str):
    """Compile the planner-executor graph for one goal. Drop-in for
    Orchestrator.agent_for so server.py streams it identically."""
    workflow = StateGraph(AgentState)
    workflow.add_node("init", init_browser_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tools_node)

    workflow.set_entry_point("init")
    workflow.add_conditional_edges("init", lambda s: "end" if s.get("errors") else "agent",
                                   {"agent": "agent", "end": END})
    workflow.add_conditional_edges("agent", router, {"tools": "tools", "agent": "agent", "end": END})
    workflow.add_conditional_edges("tools", router, {"agent": "agent", "tools": "tools", "end": END})
    return workflow.compile()


def routing_banner() -> str:
    r = describe_routing()
    return f"reasoning={r['reasoning_model']} coding={r['coding_model']} @ {r['base_url']}"
