import os
from typing import Any, Literal

from state import AgentState
from tools.resume_parser import get_resume_text
from tools.llm_models import DEFAULT_LLM_MODEL, get_ollama_base_url, resolve_model
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ConfigDict, Field, model_validator
from dotenv import load_dotenv

load_dotenv()

APPLY_THRESHOLD = int(os.getenv("APPLY_THRESHOLD", "60"))
OUTREACH_THRESHOLD = int(os.getenv("OUTREACH_THRESHOLD", "65"))

EvaluationAction = Literal["APPLY", "NETWORK", "DRAFT_EMAIL", "DRAFT_DM", "SKIP"]


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    match_score: int = Field(..., ge=0, le=100)
    reasoning: str = Field(...)
    action: EvaluationAction = Field(...)
    extracted_email: str = Field(default="")
    draft_message: str = Field(default="")

    @model_validator(mode="before")
    @classmethod
    def normalize_llm_shape(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        merged = dict(data)
        analysis = merged.pop("analysis", None)
        if isinstance(analysis, dict):
            for key in ("match_score", "reasoning", "action", "extracted_email", "draft_message"):
                if key not in merged or merged.get(key) in (None, ""):
                    val = analysis.get(key)
                    if val is not None and val != "":
                        merged[key] = val
            extra = []
            for key in ("skills_match", "experience_match", "domain_match"):
                if key in analysis:
                    extra.append(f"{key}: {analysis[key]}")
            if extra:
                bits = " | ".join(extra)
                base = str(merged.get("reasoning") or analysis.get("reasoning") or "").strip()
                merged["reasoning"] = f"{base} ({bits})" if base else bits
        for key in ("draft_message", "extracted_email", "reasoning"):
            if merged.get(key) is None:
                merged[key] = ""
        act = merged.get("action")
        if isinstance(act, str):
            upper = act.strip().upper()
            merged["action"] = upper if upper in ("APPLY", "NETWORK", "DRAFT_EMAIL", "DRAFT_DM", "SKIP") else "SKIP"
        elif act is None:
            merged["action"] = "SKIP"
        if merged.get("match_score") is None:
            merged["match_score"] = 0
        return merged


_EVAL_SYSTEM = (
    "You are a career screening assistant whose ONLY job is to apply the rules below to decide an "
    "action. You must not act as a gatekeeper or recruiter — the candidate has already decided to "
    "apply broadly. Output ONLY the structured schema, no prose outside it."
)

_EVAL_HUMAN = """Decide an action for this LinkedIn content based on the candidate profile + preferences.

Candidate Preferences (these override resume defaults):
{preferences}

Resume:
{resume}

Content to evaluate:
{content}

SCORING (0-100):
- Start at 50.
- +25 if the role's domain matches the candidate's target role (AI/ML/data/software when the candidate is in that space).
- +15 if the job's primary tech stack overlaps the candidate's resume by 2+ items (e.g. Python, LLMs, RAG, LangChain).
- +10 if the role is junior-friendly OR doesn't have an explicit seniority bar in the title (no "Senior", "Lead", "Principal", "Staff").
- -20 if the role is in a clearly unrelated domain (e.g. mechanical/electrical engineering, sales, marketing, finance, QA-only, pure DevOps when candidate is AI).
- DO NOT subtract points for "years of experience required" or seniority requirements. The candidate is willing to apply regardless of the years-of-experience line.
- DO NOT subtract points for location/workplace type if it aligns with Candidate Preferences.

ACTION RULES (mandatory — do not override with personal judgment):
- JOB: if match_score >= {apply_threshold} -> action="APPLY". Otherwise action="SKIP".
- PROFILE: if relevant to the candidate's goals -> action="NETWORK". Otherwise "SKIP".
- POST: if match_score >= {outreach_threshold} AND a contact email is found in the post (look for any "@" address) -> "DRAFT_EMAIL" (fill extracted_email AND draft_message). If match_score >= {outreach_threshold} with no email -> "DRAFT_DM" (fill draft_message only). Otherwise "SKIP".

DRAFT_MESSAGE GUIDELINES (only when action is DRAFT_EMAIL or DRAFT_DM):
- Match the LANGUAGE of the original post (French post → French message, English → English, etc.).
- Length: DRAFT_EMAIL ≈ 120-180 words, DRAFT_DM ≈ 80-120 words (LinkedIn DMs).
- Reference the SPECIFIC role title(s) and 1-2 concrete tech stack items from the post.
- Reference 1-2 concrete matching items from the candidate's resume (project/skill/experience name).
- Friendly + professional tone. No overclaiming. No emoji unless the post used them prominently.
- DRAFT_EMAIL must be a complete email body (greeting + body + sign-off with the candidate's name from the resume), no Subject line.
- DRAFT_DM must be a single message (greeting + 2-4 sentences + sign-off), no markdown, no links other than what's in the resume.
- Do NOT mention "I saw your post" generically — instead mention the specific company/team or job title from the post.
- Do NOT include placeholder tokens like [Name] or [Company] — fill them with actual values from the post and resume.

OUTPUT:
- match_score: integer 0-100.
- reasoning: 1-2 sentences citing matched skills/domain (NOT the email body — that goes in draft_message).
- action: exact value per the rules.
- extracted_email: the email address found in the post (verbatim), or empty string.
- draft_message: the full personalized email body or DM text per the guidelines, or empty string.
"""


_llm_cache: dict[tuple[str, str], Any] = {}


def _get_llm(model_name: str):
    base_url = get_ollama_base_url()
    key = (model_name, base_url)
    cached = _llm_cache.get(key)
    if cached is None:
        cached = ChatOllama(model=model_name, temperature=0, base_url=base_url)
        _llm_cache[key] = cached
    return cached


def _build_content(state: AgentState) -> str:
    if state.get("job_details"):
        return f"JOB DETAILS:\n{state['job_details']}"
    if state.get("profile_details"):
        return f"PROFILE DETAILS:\n{state['profile_details']}"
    if state.get("post_details"):
        return f"POST DETAILS:\n{state['post_details']}"
    return ""


def evaluate_node(state: AgentState) -> dict:
    content = _build_content(state)
    if not content:
        return {
            "match_score": 0,
            "reasoning": "No content to evaluate.",
            "action_taken": "SKIP",
            "extracted_email": "",
            "draft_message": "",
        }

    resume_text = get_resume_text()
    model_name = resolve_model(state.get("llm_model"))
    llm = _get_llm(model_name)

    prompt = ChatPromptTemplate.from_messages([
        ("system", _EVAL_SYSTEM),
        ("human", _EVAL_HUMAN),
    ])
    structured_llm = llm.with_structured_output(EvaluationResult, method="json_schema")
    chain = prompt | structured_llm

    preferences = (
        f"- Target Role: {state.get('search_role', 'Any')}\n"
        f"- Target Locations: {', '.join(state.get('search_locations', ['Worldwide']))}\n"
        f"- Workplace Types: {', '.join(state.get('workplace_types', ['Remote', 'Hybrid', 'On-site']))}\n"
    )
    payload = {
        "resume": resume_text,
        "content": content,
        "preferences": preferences,
        "apply_threshold": APPLY_THRESHOLD,
        "outreach_threshold": OUTREACH_THRESHOLD,
    }

    is_job = bool(state.get("job_details"))
    is_post = bool(state.get("post_details"))

    last_err: Exception | None = None
    for _ in range(3):
        try:
            result = chain.invoke(payload)
            action = result.action
            reasoning = result.reasoning

            # Force decisions to match the score band — LLM disagreements lose.
            if is_job:
                if result.match_score >= APPLY_THRESHOLD and action != "APPLY":
                    reasoning = f"[forced APPLY: score {result.match_score} >= {APPLY_THRESHOLD}] {reasoning}"
                    action = "APPLY"
                elif result.match_score < APPLY_THRESHOLD and action == "APPLY":
                    reasoning = f"[forced SKIP: score {result.match_score} < {APPLY_THRESHOLD}] {reasoning}"
                    action = "SKIP"
            elif is_post:
                if result.match_score >= OUTREACH_THRESHOLD and action == "SKIP":
                    action = "DRAFT_EMAIL" if result.extracted_email else "DRAFT_DM"
                    reasoning = f"[forced {action}: score {result.match_score} >= {OUTREACH_THRESHOLD}] {reasoning}"

            return {
                "match_score": result.match_score,
                "reasoning": reasoning,
                "action_taken": action,
                "extracted_email": result.extracted_email,
                "draft_message": result.draft_message,
            }
        except Exception as exc:
            last_err = exc

    message = f"LLM evaluation failed after retries: {last_err}"
    return {
        "match_score": 0,
        "reasoning": message,
        "action_taken": "SKIP",
        "extracted_email": "",
        "draft_message": "",
        "errors": state.get("errors", []) + [message],
    }
