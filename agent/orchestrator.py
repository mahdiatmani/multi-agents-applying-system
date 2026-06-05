"""Top-level Orchestrator — owns the capability agents and dispatches runs.

The system is three named capability agents, each a self-contained LangGraph
sub-graph compiled by `agent.graph.build_agent`:

    • Easy Apply Agent    (JOB)    search jobs   → evaluate → Easy Apply submit
    • Networking Agent     (PERSON) search people → evaluate → connect + queue DM
    • Post Outreach Agent  (POST)   scrape feed   → evaluate → email / DM / apply-link

The Orchestrator maps each user-selected mode to its agent, compiles it on
first use (cached for the process lifetime), and hands the compiled graph back
to the server runner, which streams it. Selecting multiple modes runs the
matching agents sequentially (see `plan`)."""

import os

from agent.graph import build_agent

# Human-facing names for each capability agent, keyed by search_type.
AGENT_NAMES = {
    "JOB": "Easy Apply Agent",
    "PERSON": "Networking Agent",
    "POST": "Post Outreach Agent",
}


def _agentic_enabled() -> bool:
    """AGENTIC=true switches from the legacy fixed graph to the planner-executor
    loop (agent/orchestrator_agent.py). Read at compile time so it can be toggled
    via .env without code changes; defaults off for safe rollout."""
    return os.getenv("AGENTIC", "false").strip().lower() in ("1", "true", "yes", "on")


class Orchestrator:
    """Registry + dispatcher for the three capability agents.

    Compiled sub-graphs are cached per search_type so repeated runs (and
    multi-mode runs) don't re-compile the graph every time."""

    def __init__(self) -> None:
        self._compiled: dict = {}

    def name_for(self, search_type: str) -> str:
        """Human-readable agent name for a mode (for logs / the dashboard)."""
        return AGENT_NAMES.get((search_type or "").upper(), "Agent")

    def agent_for(self, search_type: str):
        """Return the compiled graph for a mode, building it on first request and
        caching it thereafter. When AGENTIC=true, returns the planner-executor
        loop; otherwise the legacy fixed graph. Both expose the same `.stream()`
        interface so the server runner is unchanged."""
        key = (search_type or "JOB").upper()
        if key not in AGENT_NAMES:
            key = "JOB"
        cache_key = f"agentic:{key}" if _agentic_enabled() else key
        if cache_key not in self._compiled:
            if _agentic_enabled():
                from agent.orchestrator_agent import build_agentic_agent
                self._compiled[cache_key] = build_agentic_agent(key)
            else:
                self._compiled[cache_key] = build_agent(key)
        return self._compiled[cache_key]

    def plan(self, search_types) -> list[tuple[str, str]]:
        """Turn the user's selected modes into an ordered, de-duped dispatch
        plan of (search_type, agent_name) tuples the runner executes one after
        another. Unknown modes are dropped."""
        seen: set[str] = set()
        ordered: list[tuple[str, str]] = []
        for st in search_types or []:
            key = (st or "").upper()
            if key in AGENT_NAMES and key not in seen:
                seen.add(key)
                ordered.append((key, AGENT_NAMES[key]))
        return ordered


# Module-level singleton the server imports and dispatches through.
ORCHESTRATOR = Orchestrator()
