"""Namespace for skills the CodeAgent (Qwen3) generates at runtime.

Modules here are written by `agent.code_agent`, validated in a sandbox, and
hot-loaded into the running process. Each exposes a single public function whose
signature was specified by the orchestrator. Treat everything in this package as
machine-generated + audited via `state/self_heal/`; do not hand-edit.
"""
