import os
import sys
import json
import asyncio
import tempfile
import threading
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pypdf import PdfReader
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate

from agent.graph import build_graph, check_pending_connections
from agent.browser import BrowserManager, has_valid_session, do_manual_login
from tools import pending as pending_db
from tools import applications as applications_db
from tools import external_leads
from tools import outreach
from tools import apply_link
from tools import qa_overrides
from tools import run_control
from tools import human_loop
from tools.llm_models import (
    DEFAULT_LLM_MODEL,
    fetch_ollama_models,
    fetch_ollama_models_async,
    get_ollama_base_url,
    local_model_names,
    resolve_model,
)
from tools.db import get_db_data, update_stat, record_activity, reset_db
from tools.history import reset_history
from tools.cv_profile import cv_profile
from tools.profile_overrides import FIELDS as PROFILE_FIELDS, load as load_overrides, save as save_overrides

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
ALLOWED_ORIGINS = [o for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup notifiers
    loop = asyncio.get_running_loop()

    def notifier(payload: dict) -> None:
        try:
            asyncio.run_coroutine_threadsafe(log_queue.put(_stash(payload)), loop)
        except Exception:
            pass

    human_loop.set_notifier(notifier)

    # Pending-connection sweeper: every 15 min, refresh statuses and send any
    # DMs that have ripened (default 10 min since acceptance — tunable via
    # DM_RIPENING_SECONDS in graph.py).
    sweep_interval = int(os.getenv("PENDING_SWEEP_SECONDS", "900"))  # 15 min
    async def _loop():
        await asyncio.sleep(60)  # let the app settle before the first sweep
        while True:
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: check_pending_connections(headless=True))
                print(f"[pending-sweeper] sweep done: {result}", flush=True)
            except Exception as exc:
                print(f"[pending-sweeper] error: {exc}", flush=True)
            await asyncio.sleep(sweep_interval)

    sweeper_task = asyncio.create_task(_loop())
    
    yield
    
    sweeper_task.cancel()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_credentials=bool(ALLOWED_ORIGINS),
    allow_methods=["*"],
    allow_headers=["*"],
)

if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

log_queue: asyncio.Queue = asyncio.Queue()
# Recent-log ring buffer — survives across SSE reconnects so a page refresh
# can replay the live log feed instead of losing it. deque.append is atomic
# in CPython, so it's safe to populate from worker threads too.
from collections import deque  # noqa: E402
LOG_BUFFER: deque = deque(maxlen=200)


def _stash(payload: dict) -> dict:
    """Append the payload to the recent-log buffer and return it unchanged.
    Lets callers chain: `await log_queue.put(_stash(p))`."""
    try:
        LOG_BUFFER.append(payload)
    except Exception:
        pass
    return payload


active_tasks = 0
active_tasks_lock = asyncio.Lock()
_running_tasks: set[asyncio.Task] = set()


_VERBOSE_PREFIXES = (
    "[Resolve]", "[2ndPass]", "[Audit]", "[Dump]", "[form_llm]",
    "[TextInputs]", "[Radios]", "[Apply]", "[Connect]", "[Snapshot]",
    "[JOB]", "[PERSON]", "[POST]",
)
_verbose_state = {"on": False, "loop": None}
_verbose_lock = threading.Lock()


class _StdoutTap:
    """Wraps stdout: writes through to the real terminal, and forwards
    debug-prefix lines into the SSE log_queue when verbose mode is on."""

    def __init__(self, original):
        self._original = original
        self._buffer = ""
        self._buf_lock = threading.Lock()

    def write(self, text):
        try:
            self._original.write(text)
        except Exception:
            pass
        with self._buf_lock:
            self._buffer += text
            lines = self._buffer.split("\n")
            self._buffer = lines.pop()  # keep partial last line
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if not _verbose_state["on"]:
                continue
            loop = _verbose_state["loop"]
            if loop is None:
                continue
            if not any(stripped.startswith(p) for p in _VERBOSE_PREFIXES):
                continue
            payload = {"message": stripped, "type": "debug", "action": "VERBOSE"}
            try:
                asyncio.run_coroutine_threadsafe(log_queue.put(_stash(payload)), loop)
            except Exception:
                pass

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return self._original.isatty()
        except Exception:
            return False


sys.stdout = _StdoutTap(sys.stdout)


class StartRequest(BaseModel):
    search_types: list[str]
    llm_model: str = DEFAULT_LLM_MODEL
    role: str
    locations: list[str]
    workplace_types: list[str]
    company: str
    headless: bool = True
    allow_ollama_cloud: bool = Field(False, description="Reserved for future use.")
    dry_run: bool = False
    verbose: bool = False

    @field_validator("llm_model", mode="before")
    @classmethod
    def normalize_llm_model(cls, value: object) -> str:
        text = (str(value) if value is not None else "").strip()
        return text or DEFAULT_LLM_MODEL


def preview_text(value: str | None, limit: int = 700) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def detail_from_node(search_type: str, action: str, value: dict) -> dict | None:
    if action == "SEARCHED_JOB":
        details = value.get("job_details") or {}
        if not details:
            return None
        return {
            "kind": "Job",
            "search_type": search_type,
            "identifier": details.get("identifier") or details.get("source_url") or details.get("title"),
            "title": details.get("title") or "Untitled job",
            "company": details.get("company", ""),
            "location": details.get("location", ""),
            "url": details.get("source_url") or value.get("current_url", ""),
            "summary": preview_text(details.get("description")),
        }

    if action == "SEARCHED_PERSON":
        details = value.get("profile_details") or {}
        if not details:
            return None
        return {
            "kind": "Profile",
            "search_type": search_type,
            "identifier": details.get("identifier") or details.get("source_url") or details.get("name"),
            "title": details.get("name") or "Unknown profile",
            "subtitle": details.get("headline", ""),
            "url": details.get("source_url") or value.get("current_url", ""),
            "summary": preview_text(details.get("about") or details.get("experience")),
        }

    if action == "SEARCHED_POST":
        details = value.get("post_details") or {}
        if not details:
            return None
        # Prefer the actual post permalink (extracted by the JS scraper from the
        # post's "feed/update/urn:li:activity:..." anchor) over the navigation URL
        # so "Open on LinkedIn" deep-links to the post, not the home feed.
        permalink = details.get("post_url") or details.get("source_url") or value.get("current_url", "")
        return {
            "kind": "Post",
            "search_type": search_type,
            "identifier": details.get("identifier") or details.get("content"),
            "title": details.get("author") or "LinkedIn post",
            "url": permalink,
            "summary": preview_text(details.get("content")),
            "author_url": details.get("author_url", ""),
            "primary_email": details.get("primary_email", ""),
            "emails": details.get("emails") or [],
            "attached_job_url": details.get("attached_job_url", ""),
            "post_url": details.get("post_url", ""),
        }

    return None


def _persist_detail(detail: dict, evaluated: bool = False) -> None:
    try:
        kind = detail.get("kind")
        if kind == "Job":
            bucket = "jobs"
            update_stat("jobsSearched")
        else:
            bucket = "profilesPosts"
            update_stat("profilesFound")
        item = {
            "id": detail.get("identifier") or detail.get("url"),
            **detail,
        }
        record_activity(bucket, item)
        print(f"[persist] wrote {kind} id={item['id']}", flush=True)
    except Exception as exc:
        print(f"[persist] FAILED ({type(exc).__name__}): {exc}", flush=True)
        import traceback
        traceback.print_exc()


def _record_action(action: str) -> None:
    try:
        if action == "APPLIED":
            update_stat("applicationsSent")
            update_stat("applicationsAttempted")
        elif action == "APPLY_FAILED":
            update_stat("applicationsAttempted")
            update_stat("applicationsFailed")
        elif action == "EXTERNAL_LEAD":
            update_stat("externalLeads")
        elif action in ("DRAFTED_EMAIL", "DRAFTED_DM"):
            update_stat("draftsCreated")
        elif action == "EXTERNAL_LINK_RECORDED":
            update_stat("draftsCreated")  # surfaces in dashboard "Drafts" tile too
        print(f"[record_action] action={action} applied", flush=True)
    except Exception as exc:
        print(f"[record_action] FAILED ({type(exc).__name__}): {exc}", flush=True)


async def run_agent_workflow(config: StartRequest, search_type: str):
    await asyncio.to_thread(fetch_ollama_models, get_ollama_base_url())
    resolved_model = resolve_model(config.llm_model)
    await log_queue.put(_stash({
        "message": (
            f"[{search_type}] Initializing workflow - Role: {config.role}, "
            f"Locations: {config.locations} using {resolved_model} (Headless: {config.headless})"
        ),
        "type": "system",
    }))

    try:
        if config.verbose:
            with _verbose_lock:
                _verbose_state["loop"] = asyncio.get_running_loop()
                _verbose_state["on"] = True
            await log_queue.put(_stash({"message": "Verbose logs enabled — debug prefixes will stream here.", "type": "system"}))
        graph_app = build_graph()

        initial_state = {
            "search_type": search_type,
            "headless": config.headless,
            "llm_model": resolved_model,
            "search_role": config.role,
            "search_locations": config.locations,
            "workplace_types": config.workplace_types,
            "target_company": config.company,
            "current_url": "",
            "job_details": {},
            "profile_details": {},
            "post_details": {},
            "match_score": 0,
            "reasoning": "",
            "extracted_email": "",
            "draft_message": "",
            "action_taken": "",
            "errors": [],
            "iterations": 0,
            "empty_streak": 0,
            "dry_run": config.dry_run,
            "verbose": config.verbose,
        }

        await log_queue.put(_stash({"message": f"[{search_type}] Browser initializing...", "type": "info"}))

        loop = asyncio.get_running_loop()

        def execute_graph():
            last_search_detail = None
            try:
                for output in graph_app.stream(initial_state, {"recursion_limit": 500}):
                    for key, value in output.items():
                        value = value or {}
                        action = value.get("action_taken", "PROCESSING")
                        msg = f"[{search_type}] Node [{key}] executed. Action: {action}"
                        if value.get("errors"):
                            msg += f" | Errors: {value.get('errors')}"

                        log_payload = {"message": msg, "type": "info", "action": action}

                        # Post mode runs in batches: surface queue depth + the role this
                        # batch was scraped for so the Live View can show "N posts remaining".
                        if "posts_queue" in value:
                            log_payload["post_batch"] = {
                                "queue_depth": len(value.get("posts_queue") or []),
                                "batch_role": value.get("posts_batch_role", ""),
                            }

                        search_detail = detail_from_node(search_type, action, value)
                        if search_detail:
                            last_search_detail = search_detail
                            log_payload["detail"] = search_detail
                            _persist_detail(search_detail)
                        elif key == "evaluate" and last_search_detail:
                            evaluated_detail = {
                                **last_search_detail,
                                "match_score": value.get("match_score", 0),
                                "reasoning": preview_text(value.get("reasoning"), 500),
                                "recommended_action": action,
                            }
                            log_payload["detail"] = evaluated_detail
                            record_activity(
                                "jobs" if evaluated_detail.get("kind") == "Job" else "profilesPosts",
                                {"id": evaluated_detail.get("identifier") or evaluated_detail.get("url"), **evaluated_detail},
                            )

                        if action in ("APPLIED", "APPLY_FAILED", "DRAFTED_EMAIL", "DRAFTED_DM", "EXTERNAL_LEAD", "EXTERNAL_LINK_RECORDED"):
                            _record_action(action)

                        asyncio.run_coroutine_threadsafe(log_queue.put(_stash(log_payload)), loop=loop)
            except run_control.StopRequested:
                raise
            finally:
                try:
                    BrowserManager().close()
                except Exception:
                    pass

        try:
            await loop.run_in_executor(None, execute_graph)
        except run_control.StopRequested as stop_exc:
            print(f"[{search_type}] Stop honored: {stop_exc}", flush=True)
            await log_queue.put(_stash({
                "message": f"[{search_type}] Stopped by user.",
                "type": "system",
                "action": "STOPPED",
            }))

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[{search_type}] Fatal error traceback:\n{tb}")
        await log_queue.put(_stash({
            "message": f"[{search_type}] Fatal error: {str(e)}\n{tb}",
            "type": "error",
            "action": "ERROR",
        }))
    finally:
        global active_tasks
        async with active_tasks_lock:
            active_tasks -= 1
            if active_tasks <= 0:
                active_tasks = 0
                with _verbose_lock:
                    _verbose_state["on"] = False
                await log_queue.put(_stash({
                    "message": "All workflows execution completed.",
                    "type": "success",
                    "action": "DONE",
                }))


@app.get("/")
async def get_ui():
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        return HTMLResponse(
            content=(
                "<h1>Frontend not built</h1>"
                "<p>Run <code>cd frontend && npm install && npm run build</code> "
                "(or rely on the Docker stage-1 builder).</p>"
            ),
            status_code=503,
        )
    return HTMLResponse(content=index.read_text(encoding="utf-8"))


async def _drain_log_queue() -> None:
    while True:
        try:
            log_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    # Also clear the recent-log replay buffer so a new run doesn't show stale
    # entries from the previous run on a fresh page load.
    try:
        LOG_BUFFER.clear()
    except Exception:
        pass


async def run_workflows_sequentially(config: StartRequest, search_types: list[str]):
    for search_type in search_types:
        await run_agent_workflow(config, search_type)


@app.post("/api/start")
async def start_agent(req: StartRequest):
    global active_tasks
    async with active_tasks_lock:
        if active_tasks > 0:
            return JSONResponse(
                {"status": "busy", "message": "A run is already in progress. Stop it before starting another."},
                status_code=409,
            )
        if not req.search_types:
            return {"status": "error", "message": "No modes selected"}
        await _drain_log_queue()
        run_control.resume()  # clear any stale pause from a previous run
        run_control.clear_stop()  # clear any stale stop flag
        human_loop.cancel_all()  # release any leftover question waiters
        active_tasks = len(req.search_types)

    task = asyncio.create_task(run_workflows_sequentially(req, req.search_types))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)

    return {"status": "started"}


@app.get("/api/login-status")
async def login_status():
    return {"logged_in": has_valid_session()}


@app.get("/api/db")
async def api_get_db():
    return get_db_data()


@app.post("/api/db/reset")
async def api_reset_db():
    reset_db()
    reset_history()
    pending_db.reset()
    applications_db.reset()
    external_leads.reset()
    return {"status": "success", "message": "DB, history, pending connections, application counter, and external leads cleared."}


# ─── External-leads endpoints ───────────────────────────────────────────────

@app.get("/api/external-leads")
async def api_external_leads():
    return {"stats": external_leads.stats(), "items": external_leads.list_items()}


class LeadStatusRequest(BaseModel):
    identifier: str
    status: str


@app.post("/api/external-leads/status")
async def api_external_leads_status(req: LeadStatusRequest):
    ok = external_leads.set_status(req.identifier, req.status)
    if not ok:
        return JSONResponse({"error": "not_found_or_invalid_status"}, status_code=400)
    return {"status": "ok"}


class LeadIdentifier(BaseModel):
    identifier: str


@app.post("/api/external-leads/remove")
async def api_external_leads_remove(req: LeadIdentifier):
    ok = external_leads.remove(req.identifier)
    return {"status": "ok" if ok else "not_found"}


@app.post("/api/external-leads/clear")
async def api_external_leads_clear():
    external_leads.reset()
    return {"status": "ok"}


@app.get("/api/qa-overrides")
async def api_qa_overrides_get():
    return {"entries": qa_overrides.load_entries()}


@app.post("/api/qa-overrides")
async def api_qa_overrides_post(payload: dict):
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return {"status": "error", "message": "Expected JSON body { entries: [{pattern, answer}, ...] }"}
    qa_overrides.save_entries(entries)
    return {"status": "success", "entries": qa_overrides.load_entries()}


@app.post("/api/qa-overrides/reset")
async def api_qa_overrides_reset():
    qa_overrides.reset_to_defaults()
    return {"status": "success", "entries": qa_overrides.load_entries()}


@app.get("/api/pending")
async def api_pending():
    return {
        "stats": pending_db.stats(),
        "items": pending_db.list_items(),
    }


# ─── Outreach endpoints (emails + DMs + connection requests, unified view) ──

def _gmail_authed() -> bool:
    """True if token.json exists and looks like a refreshable credential file.
    Cheap check — does NOT verify the token is actually valid with Google."""
    token_path = ROOT_DIR / "token.json"
    if not token_path.exists():
        return False
    try:
        import json as _json
        with open(token_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        return bool(data.get("refresh_token") or data.get("token"))
    except Exception:
        return False


@app.get("/api/outreach")
async def api_outreach():
    """Unified outreach view: emails drafted + apply-via-link posts + connection
    requests + queued/sent DMs, with one summary stat block. `gmail_authed`
    flag drives the 'Set up Gmail auth' banner on the Outreach tab."""
    return {
        "gmail_authed": _gmail_authed(),
        "emails": {
            "items": outreach.list_items(),
            "stats": outreach.stats(),
        },
        "links": {
            "items": apply_link.list_items(),
            "stats": apply_link.stats(),
        },
        "connections": {
            "items": pending_db.list_items(),
            "stats": pending_db.stats(),
        },
    }


class ApplyLinkStatusRequest(BaseModel):
    identifier: str  # apply_url or post_url
    status: str      # new | opened | applied | dismissed


@app.post("/api/outreach/links/status")
async def api_outreach_link_status(req: ApplyLinkStatusRequest):
    ok = apply_link.set_status(req.identifier, req.status)
    if not ok:
        return JSONResponse({"error": "not_found_or_invalid_status"}, status_code=400)
    return {"status": "ok"}


class ApplyLinkIdentifier(BaseModel):
    identifier: str


@app.post("/api/outreach/links/remove")
async def api_outreach_link_remove(req: ApplyLinkIdentifier):
    ok = apply_link.remove(req.identifier)
    return {"status": "ok" if ok else "not_found"}


@app.post("/api/outreach/links/clear")
async def api_outreach_links_clear():
    apply_link.reset()
    return {"status": "ok"}


class OutreachEmailStatusRequest(BaseModel):
    identifier: str  # to_email or post_url
    status: str      # drafted | sent | replied | ignored


@app.post("/api/outreach/emails/status")
async def api_outreach_email_status(req: OutreachEmailStatusRequest):
    ok = outreach.set_status(req.identifier, req.status)
    if not ok:
        return JSONResponse({"error": "not_found_or_invalid_status"}, status_code=400)
    return {"status": "ok"}


class OutreachEmailIdentifier(BaseModel):
    identifier: str


@app.post("/api/outreach/emails/remove")
async def api_outreach_email_remove(req: OutreachEmailIdentifier):
    ok = outreach.remove(req.identifier)
    return {"status": "ok" if ok else "not_found"}


@app.post("/api/outreach/emails/clear")
async def api_outreach_emails_clear():
    outreach.reset()
    return {"status": "ok"}


@app.post("/api/pause")
async def api_pause():
    if run_control.is_paused():
        return {"status": "already_paused", "paused": True}
    run_control.pause()
    await log_queue.put(_stash({"message": "Agent paused — running nodes will block until resumed.", "type": "system", "action": "PAUSED"}))
    return {"status": "paused", "paused": True}


@app.post("/api/resume")
async def api_resume():
    if not run_control.is_paused():
        return {"status": "already_running", "paused": False}
    run_control.resume()
    await log_queue.put(_stash({"message": "Agent resumed.", "type": "system", "action": "RESUMED"}))
    return {"status": "resumed", "paused": False}


@app.get("/api/pause-status")
async def api_pause_status():
    return {"paused": run_control.is_paused()}


@app.get("/api/run-status")
async def api_run_status():
    """Snapshot of whether an agent run is currently active. Used by the frontend
    on mount so a page refresh during a run can restore the Run/Stop button
    state and re-open the SSE log stream — without this, refresh shows idle
    even though the bot is still working."""
    return {
        "is_running": active_tasks > 0,
        "is_paused": run_control.is_paused(),
        "active_tasks": active_tasks,
    }


@app.get("/api/recent-logs")
async def api_recent_logs():
    """Return the recent-log ring buffer (up to 200 most recent log payloads)
    in chronological order. Frontend loads this on mount to replay the live
    log feed across page refreshes."""
    return {"logs": list(LOG_BUFFER)}


@app.post("/api/stop")
async def api_stop():
    if not run_control.is_stopping():
        run_control.request_stop()
        cancelled = human_loop.cancel_all()
        await log_queue.put(_stash({
            "message": (
                "Stop requested — agent will halt at the next node boundary."
                + (f" Cancelled {cancelled} pending human question(s)." if cancelled else "")
            ),
            "type": "system",
            "action": "STOPPING",
        }))
    return {"status": "stopping"}


@app.get("/api/pending-questions")
async def api_pending_questions():
    return {"questions": human_loop.list_pending()}


class AnswerQuestionRequest(BaseModel):
    id: str
    answer: str = ""
    save_for_future: bool = True


@app.post("/api/answer-question")
async def api_answer_question(req: AnswerQuestionRequest):
    ok = human_loop.submit_answer(req.id, req.answer, save_for_future=req.save_for_future)
    if not ok:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return {"status": "ok"}


@app.post("/api/cancel-question")
async def api_cancel_question(req: AnswerQuestionRequest):
    ok = human_loop.cancel(req.id)
    return {"status": "ok" if ok else "not_found"}


@app.post("/api/check-pending")
async def api_check_pending():
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, lambda: check_pending_connections(headless=True))
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


@app.post("/api/login")
async def manual_login():
    username = os.getenv("LINKEDIN_USERNAME", "")
    password = os.getenv("LINKEDIN_PASSWORD", "")

    loop = asyncio.get_running_loop()

    def _do_login():
        return do_manual_login(username, password, timeout_ms=120000)

    try:
        success, message = await loop.run_in_executor(None, _do_login)
        status = "success" if success else "failed"
        return {"status": status, "message": message}
    except Exception as e:
        return {"status": "error", "message": f"Login error: {str(e)}"}


@app.get("/api/logs")
async def stream_logs(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            log = await log_queue.get()
            yield {"data": json.dumps(log)}
            if log.get("action") == "DONE":
                break

    return EventSourceResponse(event_generator())


class CVContent(BaseModel):
    content: str


class AutoTargetResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str = Field(description="Primary job title to target; concise, e.g. 'AI Engineer'.")
    locations: list[str] = Field(description="Best countries or regions to apply (e.g. ['Worldwide']).")
    workplace_types: list[str] = Field(description="Subset of: 'Remote', 'On-site', 'Hybrid'.")


class ParsedApplicantProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    first_name: str = Field(default="", description="Candidate's first/given name.")
    last_name: str = Field(default="", description="Candidate's last/family name.")
    email: str = Field(default="", description="Primary email address.")
    phone: str = Field(default="", description="Phone in international format if possible, e.g. +212...")
    city: str = Field(default="", description="Current city (no country).")
    country: str = Field(default="", description="Country of residence (e.g. 'Morocco', 'France'). If the CV says 'Rabat, Morocco', country is 'Morocco'.")
    linkedin: str = Field(default="", description="Full LinkedIn profile URL.")
    github: str = Field(default="", description="Full GitHub profile URL.")
    portfolio: str = Field(default="", description="Personal site / portfolio URL.")
    years_exp: str = Field(default="", description="Total years of professional (paid) experience as an integer string. Round up partial years. Use '1' if junior.")


async def _parse_profile_from_text(raw_text: str, model_name: str) -> dict:
    """Run an LLM extraction over raw CV text to return canonical profile fields."""
    if not raw_text or not raw_text.strip():
        return {}
    try:
        llm = ChatOllama(model=model_name, temperature=0, base_url=get_ollama_base_url())
        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "You extract canonical applicant data from a resume. Only fill fields you can confidently "
                "find in the text. Leave a field as an empty string when unsure. Return JSON matching the schema.",
            ),
            (
                "human",
                "Resume text:\n{raw_text}\n\nReturn the structured profile.",
            ),
        ])
        chain = prompt | llm.with_structured_output(ParsedApplicantProfile, method="json_schema")
        result = await chain.ainvoke({"raw_text": raw_text})
        return {k: v for k, v in result.model_dump().items() if isinstance(v, str) and v.strip()}
    except Exception as exc:
        print(f"[profile-parse] LLM extraction failed: {exc}", flush=True)
        return {}


def _merge_overrides_keep_user(parsed: dict) -> dict:
    """Merge LLM-parsed profile into existing overrides, never clobbering a user-set value."""
    existing = load_overrides()
    for key, value in parsed.items():
        if not value:
            continue
        if existing.get(key):
            continue
        existing[key] = value
    return save_overrides(existing)


@app.post("/api/auto-target")
async def auto_target(req: Request):
    data = await req.json()
    requested_model = resolve_model(data.get("llm_model"))

    cv_path = ROOT_DIR / "CV.txt"
    if not cv_path.exists():
        return {"role": "AI Engineer", "locations": ["Worldwide"], "workplace_types": ["Remote", "Hybrid"]}

    cv_text = cv_path.read_text(encoding="utf-8")

    try:
        ollama_base_url = get_ollama_base_url()
        llm = ChatOllama(model=requested_model, temperature=0, base_url=ollama_base_url)

        auto_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an expert recruiter. Read the CV and fill the required schema fields only."),
            (
                "human",
                "Infer one best target role, suitable locations (or ['Worldwide']), and workplace_types "
                "from exactly: Remote, On-site, Hybrid.\n\nCV:\n{cv}",
            ),
        ])

        structured_llm = llm.with_structured_output(AutoTargetResult, method="json_schema")
        chain = auto_prompt | structured_llm
        result = await chain.ainvoke({"cv": cv_text})

        return {"role": result.role, "locations": result.locations, "workplace_types": result.workplace_types}
    except Exception as e:
        print(f"Error in auto-target: {e}")
        return {"role": "AI Engineer", "locations": ["Worldwide"], "workplace_types": ["Remote", "Hybrid"]}


_PROFILE_ENV_KEYS = {
    "first_name": "APPLICANT_FIRST_NAME",
    "last_name": "APPLICANT_LAST_NAME",
    "email": "APPLICANT_EMAIL",
    "phone": "APPLICANT_PHONE",
    "city": "APPLICANT_CITY",
    "country": "APPLICANT_COUNTRY",
    "linkedin": "APPLICANT_LINKEDIN",
    "github": "APPLICANT_GITHUB",
    "portfolio": "APPLICANT_PORTFOLIO",
    "years_exp": "APPLICANT_YEARS_EXP",
    "authorized": "APPLICANT_AUTHORIZED",
    "sponsorship": "APPLICANT_SPONSORSHIP",
    "relocate": "APPLICANT_RELOCATE",
    "notice": "APPLICANT_NOTICE",
    "salary": "APPLICANT_SALARY",
}

_PROFILE_STATIC_DEFAULTS = {
    "authorized": "Smart: Yes when job is in Morocco, No when abroad",
    "sponsorship": "Smart: No when job is in Morocco, Yes when abroad",
    "relocate": "Yes",
    "notice": "2 weeks",
    "salary": "",
}


def _build_profile() -> dict:
    cv = cv_profile()
    overrides = load_overrides()
    out = {}
    for field in PROFILE_FIELDS:
        env_key = _PROFILE_ENV_KEYS.get(field, "")
        ov = str(overrides.get(field) or "")
        env_val = (os.getenv(env_key) or "") if env_key else ""
        cv_val = str(cv.get(field) or "") if field in cv else ""
        default = _PROFILE_STATIC_DEFAULTS.get(field, "")
        if ov:
            source = "override"
        elif env_val:
            source = "env"
        elif cv_val:
            source = "cv"
        elif default:
            source = "default"
        else:
            source = "missing"
        out[field] = {
            "value": ov or env_val or cv_val or default,
            "source": source,
            "override": ov,
            "env": env_val,
            "cv": cv_val,
            "default": default,
        }
    return out


@app.get("/api/profile")
async def get_profile():
    return _build_profile()


class ProfileSaveRequest(BaseModel):
    overrides: dict[str, str]


@app.post("/api/profile")
async def save_profile(req: ProfileSaveRequest):
    saved = save_overrides(req.overrides)
    return {"status": "saved", "overrides": saved, "profile": _build_profile()}


@app.get("/api/cv")
async def get_cv():
    cv_path = ROOT_DIR / "CV.txt"
    if cv_path.exists():
        return {"content": cv_path.read_text(encoding="utf-8")}
    return {"content": ""}


@app.post("/api/cv")
async def save_cv(cv: CVContent):
    (ROOT_DIR / "CV.txt").write_text(cv.content, encoding="utf-8")
    return {"status": "saved"}


@app.get("/api/models")
async def get_models():
    model_infos = await fetch_ollama_models_async(get_ollama_base_url())
    models = local_model_names(model_infos)
    default_model = resolve_model(DEFAULT_LLM_MODEL)

    warning = None
    if not models:
        models = [default_model]
        warning = (
            f"No local Ollama models were found. Install '{default_model}' "
            "or set DEFAULT_LLM_MODEL to an installed model."
        )

    return {"models": models, "default_model": default_model, "warning": warning}


@app.post("/api/upload-cv")
async def upload_cv(file: UploadFile = File(...), llm_model: str = Form(DEFAULT_LLM_MODEL)):
    resolved_model = resolve_model(llm_model)

    suffix = os.path.splitext(file.filename or "")[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        temp_path = tmp.name

    raw_text = ""
    try:
        reader = PdfReader(temp_path)
        for page in reader.pages:
            raw_text += (page.extract_text() or "") + "\n"
    except Exception as e:
        print(f"Error reading pdf: {e}")
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

    try:
        ollama_base_url = get_ollama_base_url()
        llm = ChatOllama(model=resolved_model, temperature=0, base_url=ollama_base_url)

        prompt = PromptTemplate.from_template(
            "You are an expert resume parser. I will give you raw, messy text extracted from a PDF resume. "
            "Your job is to parse this text, understand the structure, and output a clean, beautifully formatted Markdown resume. "
            "Do not add any conversational filler, only output the structured resume.\n\n"
            "Raw Text:\n{raw_text}"
        )

        chain = prompt | llm
        structured_text = (await chain.ainvoke({"raw_text": raw_text})).content
    except Exception as e:
        print(f"Error using LLM to parse CV: {e}")
        structured_text = raw_text

    (ROOT_DIR / "CV.txt").write_text(structured_text, encoding="utf-8")

    parsed_profile = await _parse_profile_from_text(structured_text or raw_text, resolved_model)
    applied_overrides: dict = {}
    if parsed_profile:
        applied_overrides = _merge_overrides_keep_user(parsed_profile)

    return {
        "content": structured_text,
        "parsed_profile": parsed_profile,
        "overrides": applied_overrides,
    }


@app.post("/api/profile/parse")
async def profile_parse(req: Request):
    """Re-extract profile fields from the current CV.txt via the LLM."""
    data = await req.json() if req.headers.get("content-type", "").startswith("application/json") else {}
    requested_model = resolve_model((data or {}).get("llm_model"))
    cv_path = ROOT_DIR / "CV.txt"
    if not cv_path.exists():
        return {"status": "no_cv", "parsed_profile": {}}
    parsed = await _parse_profile_from_text(cv_path.read_text(encoding="utf-8"), requested_model)
    applied = _merge_overrides_keep_user(parsed) if parsed else load_overrides()
    return {
        "status": "ok",
        "parsed_profile": parsed,
        "overrides": applied,
        "profile": _build_profile(),
    }


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8000"))
    print(f"Starting Web UI on http://{host}:{port}")
    uvicorn.run("server:app", host=host, port=port, reload=True)
