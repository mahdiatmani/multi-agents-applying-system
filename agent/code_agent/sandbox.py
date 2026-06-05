"""Static + dynamic safety gate for CodeAgent-generated skills.

NOTHING the CodeAgent writes touches the live LinkedIn session until it has:
  1. parsed as valid Python (AST),
  2. passed a static scan — no imports outside the allowlist, no dangerous calls
     (eval/exec/compile, os.system, subprocess, socket, arbitrary file writes,
     __import__), and
  3. executed its acceptance test in a *separate, time-limited subprocess*
     against a captured fixture (never the live page).

This is the floor under runtime self-coding. It is intentionally conservative:
a rejected candidate is safer than a clever one.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field

# Modules a generated skill may import without extra approval. Playwright/bs4 are
# the bread-and-butter of scrapers; re/json/typing/urllib.parse are pure-stdlib
# parsing helpers. Anything else must be explicitly allow-listed per-spec.
_BASE_ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {
        "re", "json", "typing", "dataclasses", "datetime", "math", "itertools",
        "collections", "urllib.parse", "html", "unicodedata", "string",
        "bs4", "playwright", "playwright.sync_api",
    }
)

# Attribute/name calls that are forbidden outright.
_FORBIDDEN_CALLS: frozenset[str] = frozenset(
    {
        "eval", "exec", "compile", "__import__", "open", "input",
        "system", "popen", "spawn", "fork", "remove", "unlink", "rmtree",
        "Popen", "run", "call", "check_output", "getoutput",
    }
)

# Modules whose mere import is forbidden regardless of allowlist.
_FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {
        "os", "sys", "subprocess", "socket", "shutil", "ctypes", "pickle",
        "marshal", "importlib", "pathlib", "requests", "httpx", "urllib.request",
    }
)


@dataclass
class GateResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


def _root_module(name: str) -> str:
    return name.split(".")[0]


def static_check(code: str, allowed_extra: frozenset[str] | set[str] | None = None) -> GateResult:
    """AST-level scan. Returns a GateResult with every reason it would reject."""
    reasons: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return GateResult(ok=False, reasons=[f"syntax error: {exc}"])

    allowed = set(_BASE_ALLOWED_IMPORTS) | set(allowed_extra or set())

    for node in ast.walk(tree):
        # Imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                if mod in _FORBIDDEN_IMPORTS or _root_module(mod) in _FORBIDDEN_IMPORTS:
                    reasons.append(f"forbidden import: {mod}")
                elif mod not in allowed and _root_module(mod) not in allowed:
                    reasons.append(f"import not allow-listed: {mod}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in _FORBIDDEN_IMPORTS or _root_module(mod) in _FORBIDDEN_IMPORTS:
                reasons.append(f"forbidden import-from: {mod}")
            elif mod and mod not in allowed and _root_module(mod) not in allowed:
                reasons.append(f"import-from not allow-listed: {mod}")
        # Calls
        elif isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in _FORBIDDEN_CALLS:
                reasons.append(f"forbidden call: {name}")
        # Dunder attribute access used to escape the sandbox
        elif isinstance(node, ast.Attribute):
            if node.attr in {"__globals__", "__builtins__", "__subclasses__", "__bases__", "__mro__"}:
                reasons.append(f"forbidden attribute access: {node.attr}")

    return GateResult(ok=not reasons, reasons=reasons)


def _has_public_fn(code: str, function_name: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    return any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function_name
        for n in tree.body
    )


def run_acceptance(
    code: str,
    function_name: str,
    acceptance_test: str,
    *,
    timeout: float = 20.0,
) -> GateResult:
    """Execute `acceptance_test` against the generated function in an isolated
    subprocess. The test must import the function as `fn` and assert on it.

    The candidate module + a harness are written to a temp dir; the subprocess
    imports the module, binds `fn = module.<function_name>`, runs the test, and
    exits non-zero on any assertion/exception. We capture stdout/stderr for the
    audit log. A timeout is treated as failure (an infinite loop is a reject)."""
    if not acceptance_test.strip():
        # No test supplied → we can't dynamically prove it; static-only pass is
        # the caller's risk decision. Signal that explicitly.
        return GateResult(ok=True, reasons=["no acceptance test — static-only"], stdout="", stderr="")

    if not _has_public_fn(code, function_name):
        return GateResult(ok=False, reasons=[f"function {function_name!r} not defined at module top level"])

    with tempfile.TemporaryDirectory(prefix="codeagent_") as tmp:
        mod_path = os.path.join(tmp, "candidate.py")
        with open(mod_path, "w", encoding="utf-8") as fh:
            fh.write(code)

        harness = textwrap.dedent(
            f"""
            import importlib.util, sys, traceback
            spec = importlib.util.spec_from_file_location("candidate", {mod_path!r})
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
                fn = getattr(mod, {function_name!r})
            except Exception:
                traceback.print_exc()
                sys.exit(2)
            try:
{textwrap.indent(acceptance_test, " " * 16)}
            except Exception:
                traceback.print_exc()
                sys.exit(1)
            print("ACCEPTANCE_OK")
            """
        )
        harness_path = os.path.join(tmp, "harness.py")
        with open(harness_path, "w", encoding="utf-8") as fh:
            fh.write(harness)

        try:
            proc = subprocess.run(
                [sys.executable, harness_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp,
            )
        except subprocess.TimeoutExpired as exc:
            return GateResult(ok=False, reasons=[f"acceptance test timed out after {timeout}s"], stderr=str(exc))

        ok = proc.returncode == 0 and "ACCEPTANCE_OK" in (proc.stdout or "")
        reasons = [] if ok else [f"acceptance test failed (exit {proc.returncode})"]
        return GateResult(ok=ok, reasons=reasons, stdout=proc.stdout or "", stderr=proc.stderr or "")


def full_gate(
    code: str,
    function_name: str,
    acceptance_test: str,
    *,
    allowed_extra: frozenset[str] | set[str] | None = None,
    timeout: float = 20.0,
) -> GateResult:
    """Static check, then (only if it passes) the dynamic acceptance test."""
    static = static_check(code, allowed_extra)
    if not static.ok:
        return static
    dyn = run_acceptance(code, function_name, acceptance_test, timeout=timeout)
    # Merge the "static-only" note through when there was no test.
    if dyn.ok and dyn.reasons:
        return GateResult(ok=True, reasons=static.reasons + dyn.reasons, stdout=dyn.stdout, stderr=dyn.stderr)
    return dyn
