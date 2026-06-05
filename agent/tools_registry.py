"""Tool registry — the agent's callable surface.

Every capability the orchestrator (GPT-OSS) can invoke is a `ToolSpec`: a name, a
JSON-schema for its args (so it can be handed to `bind_tools`), the `TaskKind`
that routes it, a handler, and the set of *goals* that may see it. The per-goal
subset preserves the old safety property — the JOB goal can't reach
`connect_and_queue_dm`, the POST goal can't reach `easy_apply` — now enforced by
tool visibility instead of hardcoded graph edges.

Handlers reuse the existing tool layer (`tools/*`, `agent/nodes`) rather than
reimplementing anything; they return a `ToolResult` the orchestrator folds into
its scratchpad. The `code_agent` tool is what makes the system self-extending:
the planner calls it whenever a step needs source code written or repaired, and
it is routed to the CODING_MODEL (Qwen3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from agent.messages import CodeSpec, ToolResult
from tools.model_router import TaskKind

# Goal identifiers (one per legacy mode + a shared "any").
GOAL_JOB = "JOB"
GOAL_PERSON = "PERSON"
GOAL_POST = "POST"
ALL_GOALS = frozenset({GOAL_JOB, GOAL_PERSON, GOAL_POST})


@dataclass
class ToolSpec:
    name: str
    description: str
    task_kind: TaskKind
    handler: Callable[[dict, dict], ToolResult]  # (args, ctx) -> ToolResult
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    goals: frozenset = ALL_GOALS

    def schema(self) -> dict:
        """OpenAI/Ollama function-tool schema for bind_tools."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    _REGISTRY[spec.name] = spec


def get(name: str) -> ToolSpec | None:
    return _REGISTRY.get(name)


def tools_for_goal(goal: str) -> list[ToolSpec]:
    g = (goal or "").upper()
    return [s for s in _REGISTRY.values() if g in s.goals]


def schemas_for_goal(goal: str) -> list[dict]:
    return [s.schema() for s in tools_for_goal(goal)]


def execute(name: str, args: dict, ctx: dict) -> ToolResult:
    """Dispatch a tool call. Unknown tools and handler exceptions both come back
    as a non-ok ToolResult so the orchestrator can reflect rather than crash."""
    spec = _REGISTRY.get(name)
    if spec is None:
        return ToolResult(tool=name, ok=False, error="unknown tool", observation=f"No tool named {name!r}.")
    try:
        return spec.handler(args or {}, ctx or {})
    except Exception as exc:  # noqa: BLE001 — surface everything to the planner
        return ToolResult(tool=name, ok=False, error=str(exc), observation=f"{name} raised {type(exc).__name__}: {exc}")


# ── Browser helper ────────────────────────────────────────────────────────────
def _page(ctx: dict):
    """Lazily get the shared Playwright page, matching how the legacy nodes do it."""
    from agent.browser import BrowserManager

    state = ctx.get("state", {})
    bm = BrowserManager(headless=state.get("headless", True))
    return bm.get_page()


# ── Handlers ──────────────────────────────────────────────────────────────────
def _h_search_jobs(args: dict, ctx: dict) -> ToolResult:
    from tools.playwright_actions import search_jobs

    page = _page(ctx)
    url = search_jobs(
        page,
        args.get("role", "AI Engineer"),
        args.get("locations", ["Worldwide"]),
        args.get("workplace_types", ["Remote"]),
        start=int(args.get("start", 0) or 0),
    )
    return ToolResult(tool="search_jobs", ok=True, value={"search_url": url}, observation=f"Searched jobs → {url}")


def _h_get_job_details(args: dict, ctx: dict) -> ToolResult:
    from tools.playwright_actions import get_job_details

    details = get_job_details(_page(ctx)) or {}
    obs = f"Job: {details.get('title','?')} @ {details.get('company','?')}" if details else "No job details extracted."
    return ToolResult(tool="get_job_details", ok=bool(details), value=details, observation=obs)


def _h_search_people(args: dict, ctx: dict) -> ToolResult:
    from tools.playwright_actions import search_people

    url = search_people(_page(ctx), args.get("company", ""), args.get("role", "AI Engineer"))
    return ToolResult(tool="search_people", ok=True, value={"search_url": url}, observation=f"Searched people → {url}")


def _h_extract_profile(args: dict, ctx: dict) -> ToolResult:
    from tools.playwright_actions import extract_profile_details

    details = extract_profile_details(_page(ctx)) or {}
    return ToolResult(
        tool="extract_profile_details",
        ok=bool(details.get("name")),
        value=details,
        observation=f"Profile: {details.get('name','?')}",
    )


def _h_scrape_feed(args: dict, ctx: dict) -> ToolResult:
    from tools.post_extractor import scrape_feed_via_js

    posts = scrape_feed_via_js(_page(ctx)) or []
    return ToolResult(
        tool="scrape_feed",
        ok=bool(posts),
        value={"posts": posts, "count": len(posts)},
        observation=f"Scraped {len(posts)} posts from the feed.",
    )


def _h_evaluate_fit(args: dict, ctx: dict) -> ToolResult:
    """Score the current content (job/profile/post) + decide an action. Reuses the
    legacy evaluators in agent.nodes, which already route JOB/PROFILE/POST."""
    from agent.nodes import evaluate_node

    state = dict(ctx.get("state", {}))
    # Allow the planner to pass the item to evaluate inline.
    for k in ("job_details", "profile_details", "post_details"):
        if k in args:
            state[k] = args[k]
    out = evaluate_node(state)
    return ToolResult(
        tool="evaluate_fit",
        ok=True,
        value=out,
        observation=f"score={out.get('match_score')} action={out.get('action_taken')} — {out.get('reasoning','')[:140]}",
    )


def _h_code_agent(args: dict, ctx: dict) -> ToolResult:
    """Delegate a coding task to the Qwen3 CodeAgent: generate/repair a tool,
    sandbox-validate, (optionally await approval), hot-load, persist."""
    from agent.code_agent import generate_tool

    try:
        spec = CodeSpec(
            goal=args["goal"],
            function_name=args["function_name"],
            signature=args["signature"],
            task_kind=TaskKind(args.get("task_kind", TaskKind.CODE_GEN.value)),
            context=args.get("context", ""),
            acceptance_test=args.get("acceptance_test", ""),
            failure_signature=args.get("failure_signature", ""),
            allowed_imports=args.get("allowed_imports", []),
        )
    except Exception as exc:
        return ToolResult(tool="code_agent", ok=False, error=str(exc), observation=f"bad CodeSpec: {exc}")

    outcome = generate_tool(spec, llm_override=ctx.get("state", {}).get("coding_model"))
    ok = outcome.status in ("loaded", "recalled")
    # Register the hot-loaded skill so subsequent steps can call it by name.
    if ok and outcome.func is not None and outcome.handle is not None:
        register(
            ToolSpec(
                name=outcome.handle.name,
                description=f"Generated skill: {spec.goal}",
                task_kind=TaskKind.ORCHESTRATE,
                handler=_make_generated_handler(outcome.func),
                parameters={"type": "object", "properties": {}, "additionalProperties": True},
                goals=ALL_GOALS,
            )
        )
    return ToolResult(
        tool="code_agent",
        ok=ok,
        value={"status": outcome.status, "detail": outcome.detail,
               "handle": outcome.handle.model_dump() if outcome.handle else None},
        error="" if ok else outcome.detail,
        observation=f"CodeAgent {outcome.status}: {outcome.detail or spec.function_name}",
    )


def _make_generated_handler(func: Callable[..., Any]) -> Callable[[dict, dict], ToolResult]:
    def _handler(args: dict, ctx: dict) -> ToolResult:
        kwargs = dict(args)
        if "page" in (getattr(func, "__code__", None).co_varnames if hasattr(func, "__code__") else ()):
            kwargs["page"] = _page(ctx)
        value = func(**kwargs)
        return ToolResult(tool=getattr(func, "__name__", "generated"), ok=True, value=value,
                          observation=f"generated skill returned {type(value).__name__}")

    return _handler


def _h_recall_skill(args: dict, ctx: dict) -> ToolResult:
    from agent.memory import recall

    handle = recall(args.get("failure_signature", ""))
    return ToolResult(
        tool="recall_skill",
        ok=handle is not None,
        value=handle.model_dump() if handle else None,
        observation="recalled a known skill" if handle else "no skill for that signature",
    )


def _action_via_node(node_name: str, node_fn, args: dict, ctx: dict) -> ToolResult:
    """Run a legacy action node (apply/network/draft_*) by composing a state from
    the run context + the item passed by the planner. This reuses ALL the existing
    safety: daily caps, dry-run, lead capture, manual-DM-only, pending dedup."""
    state = dict(ctx.get("state", {}))
    for k in ("job_details", "profile_details", "post_details",
              "draft_message", "draft_subject", "extracted_email", "apply_url", "match_score"):
        if k in args:
            state[k] = args[k]
    out = node_fn(state) or {}
    action = out.get("action_taken", "")
    ok = action not in ("APPLY_FAILED", "NETWORK_FAILED", "DRAFT_FAILED", "EXTERNAL_LINK_FAILED")
    return ToolResult(
        tool=node_name, ok=ok, value=out,
        observation=f"{node_name} → {action}" + (f" ({out['errors'][-1]})" if out.get("errors") else ""),
    )


def _h_easy_apply(args: dict, ctx: dict) -> ToolResult:
    from agent.graph import apply_node
    return _action_via_node("easy_apply", apply_node, args, ctx)


def _h_connect_and_queue_dm(args: dict, ctx: dict) -> ToolResult:
    from agent.graph import network_node
    return _action_via_node("connect_and_queue_dm", network_node, args, ctx)


def _h_draft_email(args: dict, ctx: dict) -> ToolResult:
    from agent.graph import draft_email_node
    return _action_via_node("draft_email", draft_email_node, args, ctx)


def _h_draft_dm(args: dict, ctx: dict) -> ToolResult:
    from agent.graph import draft_dm_node
    return _action_via_node("draft_dm", draft_dm_node, args, ctx)


def _h_record_apply_link(args: dict, ctx: dict) -> ToolResult:
    from agent.graph import external_link_node
    return _action_via_node("record_apply_link", external_link_node, args, ctx)


# ── Registration ──────────────────────────────────────────────────────────────
def _build_registry() -> None:
    register(ToolSpec(
        name="search_jobs", description="Run a LinkedIn job search and load the results page.",
        task_kind=TaskKind.ORCHESTRATE, handler=_h_search_jobs, goals=frozenset({GOAL_JOB}),
        parameters={"type": "object", "properties": {
            "role": {"type": "string"}, "locations": {"type": "array", "items": {"type": "string"}},
            "workplace_types": {"type": "array", "items": {"type": "string"}}, "start": {"type": "integer"}},
        }))
    register(ToolSpec(
        name="get_job_details", description="Open the selected job card and extract its full details.",
        task_kind=TaskKind.ORCHESTRATE, handler=_h_get_job_details, goals=frozenset({GOAL_JOB})))
    register(ToolSpec(
        name="search_people", description="Run a LinkedIn people search (optionally scoped to a company).",
        task_kind=TaskKind.ORCHESTRATE, handler=_h_search_people, goals=frozenset({GOAL_PERSON}),
        parameters={"type": "object", "properties": {"company": {"type": "string"}, "role": {"type": "string"}}}))
    register(ToolSpec(
        name="extract_profile_details", description="Extract the currently open LinkedIn profile.",
        task_kind=TaskKind.ORCHESTRATE, handler=_h_extract_profile, goals=frozenset({GOAL_PERSON})))
    register(ToolSpec(
        name="scrape_feed", description="Scrape the LinkedIn home feed for posts (content-anchored JS scraper).",
        task_kind=TaskKind.ORCHESTRATE, handler=_h_scrape_feed, goals=frozenset({GOAL_POST})))
    register(ToolSpec(
        name="evaluate_fit",
        description="Score the current job/profile/post against the CV and decide an action.",
        task_kind=TaskKind.EVALUATE, handler=_h_evaluate_fit, goals=ALL_GOALS,
        parameters={"type": "object", "properties": {
            "job_details": {"type": "object"}, "profile_details": {"type": "object"},
            "post_details": {"type": "object"}}}))
    register(ToolSpec(
        name="code_agent",
        description=("Write or repair a Python tool with the coding model (Qwen3). Use whenever a step needs "
                     "new source code: a broken selector/scraper, a new ATS form handler, a parsing script. "
                     "Provide a goal, the exact function_name + signature, grounding context (a DOM dump or "
                     "stack trace), and an acceptance_test."),
        task_kind=TaskKind.CODE_GEN, handler=_h_code_agent, goals=ALL_GOALS,
        parameters={"type": "object", "properties": {
            "goal": {"type": "string"}, "function_name": {"type": "string"},
            "signature": {"type": "string"}, "context": {"type": "string"},
            "acceptance_test": {"type": "string"}, "failure_signature": {"type": "string"},
            "task_kind": {"type": "string"},
            "allowed_imports": {"type": "array", "items": {"type": "string"}}},
            "required": ["goal", "function_name", "signature"]}))
    register(ToolSpec(
        name="recall_skill", description="Look up a previously generated skill by failure signature.",
        task_kind=TaskKind.ORCHESTRATE, handler=_h_recall_skill, goals=ALL_GOALS,
        parameters={"type": "object", "properties": {"failure_signature": {"type": "string"}},
                    "required": ["failure_signature"]}))

    # ── Action tools (delegate to legacy nodes → keep all caps/dry-run/leads) ──
    register(ToolSpec(
        name="easy_apply", description="Submit a LinkedIn Easy Apply for the given job (respects daily cap).",
        task_kind=TaskKind.ORCHESTRATE, handler=_h_easy_apply, goals=frozenset({GOAL_JOB}),
        parameters={"type": "object", "properties": {"job_details": {"type": "object"}}}))
    register(ToolSpec(
        name="connect_and_queue_dm",
        description="Send an empty connection invite and queue a personalized DM draft (never auto-sent).",
        task_kind=TaskKind.ORCHESTRATE, handler=_h_connect_and_queue_dm, goals=frozenset({GOAL_PERSON}),
        parameters={"type": "object", "properties": {
            "profile_details": {"type": "object"}, "draft_message": {"type": "string"}}}))
    register(ToolSpec(
        name="draft_email", description="Create a Gmail draft to the extracted address with the CV attached.",
        task_kind=TaskKind.ORCHESTRATE, handler=_h_draft_email, goals=frozenset({GOAL_POST}),
        parameters={"type": "object", "properties": {
            "extracted_email": {"type": "string"}, "draft_message": {"type": "string"},
            "draft_subject": {"type": "string"}, "post_details": {"type": "object"}}}))
    register(ToolSpec(
        name="draft_dm",
        description="Connect to a post author and queue a DM draft for manual send (never auto-sent).",
        task_kind=TaskKind.ORCHESTRATE, handler=_h_draft_dm, goals=frozenset({GOAL_POST}),
        parameters={"type": "object", "properties": {
            "draft_message": {"type": "string"}, "post_details": {"type": "object"}}}))
    register(ToolSpec(
        name="record_apply_link", description="Persist an external/ATS apply link from a hiring post for manual review.",
        task_kind=TaskKind.ORCHESTRATE, handler=_h_record_apply_link, goals=frozenset({GOAL_POST}),
        parameters={"type": "object", "properties": {
            "apply_url": {"type": "string"}, "post_details": {"type": "object"}}}))


_build_registry()
