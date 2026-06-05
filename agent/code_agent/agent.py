"""CodeAgent — generates/repairs a single-function tool with the CODING_MODEL
(Qwen3-coder), gates it, and hot-loads it into the running process.

Pipeline (matches the agreed design):
    recall ─▶ generate(Qwen3) ─▶ static+sandbox gate ─▶ approval gate
           ─▶ write tools/generated/<slug>.py ─▶ hot-import ─▶ persist skill

`generate_tool(spec)` is the single entrypoint. It returns a CodeAgentOutcome the
orchestrator inspects: on `status == "loaded"` the new callable is ready in
`outcome.func`; on `"awaiting_approval"` a diff is queued for the dashboard; on
`"rejected"`/`"error"` the orchestrator falls back (lead/skip) as it does today.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import textwrap
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field

from langchain_core.prompts import ChatPromptTemplate

from agent.code_agent.sandbox import full_gate, GateResult
from agent.memory import recall, remember
from agent.messages import CodeSpec, ToolHandle
from tools.model_router import TaskKind, llm_for

_HERE = os.path.dirname(__file__)
_GENERATED_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "tools", "generated"))
_AUDIT_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "state", "self_heal"))


def _require_approval() -> bool:
    val = os.getenv("SELF_CODING_REQUIRE_APPROVAL", "true").strip().lower()
    return val in ("1", "true", "yes", "on")


# ── Generation schema ─────────────────────────────────────────────────────────
class GeneratedCode(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str = Field(..., description="A complete Python module exposing exactly the requested function.")
    explanation: str = Field(default="", description="One paragraph on the approach.")


_SYSTEM = (
    "You are a precise Python tool-writer for a browser-automation agent. You output ONE self-contained "
    "module that defines exactly the requested function and nothing that runs at import time. "
    "Hard rules:\n"
    "  • Define the function at module top level with the EXACT name and signature requested.\n"
    "  • Only import from: re, json, typing, dataclasses, urllib.parse, html, unicodedata, bs4, "
    "playwright. NEVER import os, sys, subprocess, socket, shutil, requests, httpx, importlib, pathlib.\n"
    "  • NEVER call eval/exec/compile/__import__/open/system/Popen or write files.\n"
    "  • Be defensive: wrap fragile DOM/parse operations in try/except and return safe defaults.\n"
    "  • No top-level side effects, no prints, no network calls beyond the passed-in Playwright `page`.\n"
    "Output ONLY the structured schema."
)

_HUMAN = """Write a Python tool.

GOAL:
{goal}

FUNCTION TO EXPOSE (exact name + signature):
    def {signature}

CONTEXT (DOM sample / stack trace / examples — ground your code in this):
{context}

ACCEPTANCE TEST it must pass (your function is imported as `fn`):
{acceptance_test}

Return the full module in `code`."""


_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    m = _CODE_BLOCK_RE.search(text or "")
    return (m.group(1) if m else (text or "")).strip()


def _generate(spec: CodeSpec, llm_override: Optional[str]) -> tuple[Optional[str], str]:
    """Call Qwen3 for the module source. Returns (code, explanation). Falls back to
    raw-text code-fence extraction when structured output fails to parse — Ollama
    coding models sometimes return a fenced block instead of strict JSON."""
    llm = llm_for(spec.task_kind or TaskKind.CODE_GEN, override=llm_override)
    prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])
    payload = {
        "goal": spec.goal,
        "signature": spec.signature,
        "context": (spec.context or "(none provided)")[:6000],
        "acceptance_test": spec.acceptance_test or "(none — static checks only)",
    }
    # Structured first.
    try:
        chain = prompt | llm.with_structured_output(GeneratedCode, method="json_schema")
        result = chain.invoke(payload)
        code = _strip_code_fence(result.code)
        if code:
            return code, (result.explanation or "")
    except Exception:
        pass
    # Raw fallback.
    try:
        raw = (prompt | llm).invoke(payload)
        text = getattr(raw, "content", None) or str(raw)
        code = _strip_code_fence(text)
        return (code or None), ""
    except Exception as exc:
        return None, f"generation failed: {exc}"


def _slug(spec: CodeSpec) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (spec.function_name or "skill").lower()).strip("_") or "skill"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{stamp}"


def _write_module(code: str, slug: str) -> str:
    os.makedirs(_GENERATED_DIR, exist_ok=True)
    path = os.path.join(_GENERATED_DIR, f"{slug}.py")
    header = (
        f"# AUTO-GENERATED by CodeAgent on {datetime.now().isoformat()}.\n"
        f"# Do not hand-edit. Validated via state/self_heal audit trail.\n\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header + code)
    return path


def _hot_load(path: str, function_name: str, slug: str) -> Callable[..., Any]:
    """Import the freshly written module from tools/generated and return the
    requested callable. Uses the package-qualified name so relative-import-free
    modules resolve cleanly, then falls back to spec-based loading."""
    module_name = f"tools.generated.{slug}"
    try:
        mod = importlib.import_module(module_name)
        importlib.reload(mod)  # ensure we get fresh source if the name was reused
    except Exception:
        spec_obj = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec_obj)
        spec_obj.loader.exec_module(mod)  # type: ignore[union-attr]
    fn = getattr(mod, function_name)
    if not callable(fn):
        raise TypeError(f"{function_name} in {path} is not callable")
    return fn


def _audit(spec: CodeSpec, code: str, gate: GateResult, status: str) -> None:
    try:
        os.makedirs(_AUDIT_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(_AUDIT_DIR, f"codeagent-{stamp}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"# CodeAgent: {spec.function_name}\n\n")
            fh.write(f"- status: **{status}**\n- failure_signature: `{spec.failure_signature}`\n")
            fh.write(f"- goal: {spec.goal}\n- gate.ok: {gate.ok}\n")
            if gate.reasons:
                fh.write(f"- gate.reasons: {gate.reasons}\n")
            if gate.stderr:
                fh.write(f"\n## sandbox stderr\n```\n{gate.stderr[:2000]}\n```\n")
            fh.write(f"\n## generated code\n```python\n{code[:8000]}\n```\n")
    except Exception:
        pass


@dataclass
class CodeAgentOutcome:
    status: str  # "loaded" | "awaiting_approval" | "rejected" | "error" | "recalled"
    handle: Optional[ToolHandle] = None
    func: Optional[Callable[..., Any]] = None
    code: str = ""
    detail: str = ""
    gate: Optional[GateResult] = None


def generate_tool(spec: CodeSpec, *, llm_override: Optional[str] = None) -> CodeAgentOutcome:
    """The single entrypoint. Recall first; otherwise generate → gate → (approve) →
    hot-load → persist."""
    # 1. Skill recall — turn a 30s codegen into a dict lookup + reload.
    if spec.failure_signature:
        cached = recall(spec.failure_signature)
        if cached is not None and cached.approved:
            try:
                slug = os.path.splitext(os.path.basename(cached.module_path))[0]
                fn = _hot_load(cached.module_path, cached.function_name, slug)
                return CodeAgentOutcome(status="recalled", handle=cached, func=fn, detail="recalled known skill")
            except Exception:
                pass  # fall through to regenerate if the cached module won't load

    # 2. Generate with Qwen3.
    code, explanation = _generate(spec, llm_override)
    if not code:
        return CodeAgentOutcome(status="error", detail=explanation or "no code produced")

    # 3. Gate: static scan + sandboxed acceptance test against the fixture.
    allowed_extra = set(spec.allowed_imports or [])
    gate = full_gate(
        code,
        spec.function_name,
        spec.acceptance_test,
        allowed_extra=allowed_extra,
    )
    if not gate.ok:
        _audit(spec, code, gate, "rejected")
        return CodeAgentOutcome(status="rejected", code=code, detail="; ".join(gate.reasons), gate=gate)

    # 4. Write the module (always — so the audit/diff exists even when gated).
    slug = _slug(spec)
    path = _write_module(code, slug)
    excerpt = "\n".join(code.splitlines()[:12])
    handle = ToolHandle(
        name=spec.function_name,
        module_path=path,
        function_name=spec.function_name,
        signature=spec.signature,
        failure_signature=spec.failure_signature,
        source_excerpt=excerpt,
    )

    # 5. Approval gate — when required, do NOT hot-load; queue the diff.
    if _require_approval():
        handle.approved = False
        _audit(spec, code, gate, "awaiting_approval")
        return CodeAgentOutcome(
            status="awaiting_approval",
            handle=handle,
            code=code,
            detail="approval required (SELF_CODING_REQUIRE_APPROVAL=true)",
            gate=gate,
        )

    # 6. Hot-load + persist.
    try:
        fn = _hot_load(path, spec.function_name, slug)
    except Exception as exc:
        _audit(spec, code, gate, "error")
        return CodeAgentOutcome(status="error", handle=handle, code=code, detail=f"hot-load failed: {exc}", gate=gate)

    remember(handle, summary=explanation[:200])
    _audit(spec, code, gate, "loaded")
    return CodeAgentOutcome(status="loaded", handle=handle, func=fn, code=code, gate=gate)


def approve(handle: ToolHandle) -> CodeAgentOutcome:
    """Promote a previously gated skill once a human approves it in the dashboard:
    hot-load the already-written module, persist, and return the live callable."""
    try:
        slug = os.path.splitext(os.path.basename(handle.module_path))[0]
        fn = _hot_load(handle.module_path, handle.function_name, slug)
    except Exception as exc:
        return CodeAgentOutcome(status="error", handle=handle, detail=f"hot-load failed: {exc}")
    handle.approved = True
    remember(handle, summary="approved by user")
    return CodeAgentOutcome(status="loaded", handle=handle, func=fn)
