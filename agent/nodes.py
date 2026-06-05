import os
import re
import json
from typing import Any, Literal

from state import AgentState
from tools.resume_parser import get_resume_text
from tools.llm_models import get_ollama_base_url, resolve_model
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ConfigDict, Field, model_validator
from dotenv import load_dotenv

load_dotenv()

APPLY_THRESHOLD = int(os.getenv("APPLY_THRESHOLD", "60"))
OUTREACH_THRESHOLD = int(os.getenv("OUTREACH_THRESHOLD", "65"))

EvaluationAction = Literal["APPLY", "NETWORK", "DRAFT_EMAIL", "DRAFT_DM", "EXTERNAL_LINK", "SKIP"]
ContactMode = Literal["EMAIL", "LINK", "DM", "NONE"]


class EvaluationResult(BaseModel):
    """Final evaluator output handed to the router. Shape preserved from the legacy
    single-call evaluator so the router/graph keep working unchanged."""
    model_config = ConfigDict(extra="ignore")

    match_score: int = Field(..., ge=0, le=100)
    reasoning: str = Field(...)
    action: EvaluationAction = Field(...)
    extracted_email: str = Field(default="")
    apply_url: str = Field(default="")
    draft_message: str = Field(default="")

    @model_validator(mode="before")
    @classmethod
    def coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        for k in ("reasoning", "extracted_email", "apply_url", "draft_message"):
            if d.get(k) is None:
                d[k] = ""
        if d.get("match_score") is None:
            d["match_score"] = 0
        act = d.get("action")
        if isinstance(act, str):
            up = act.strip().upper()
            if up not in ("APPLY", "NETWORK", "DRAFT_EMAIL", "DRAFT_DM", "EXTERNAL_LINK", "SKIP"):
                up = "SKIP"
            d["action"] = up
        elif act is None:
            d["action"] = "SKIP"
        return d


# ─────────────────────────── Job / Profile prompts (unchanged shape) ───────────────────────────

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

OUTPUT:
- match_score: integer 0-100.
- reasoning: 1-2 sentences citing matched skills/domain.
- action: exact value per the rules.
- extracted_email: empty string for JOB/PROFILE.
- apply_url: empty string for JOB/PROFILE.
- draft_message: empty string for JOB/PROFILE.
"""


# ───────────────────────────── Two-stage POST evaluation ─────────────────────────────────────

class HiringCheck(BaseModel):
    """Stage 1: is this even a hiring/recruitment post?"""
    model_config = ConfigDict(extra="ignore")
    is_hiring: bool = Field(..., description="True only if the post is offering a job, internship, contract or actively asking candidates to apply.")
    reasoning: str = Field(default="", description="One sentence explaining the verdict.")

    @model_validator(mode="before")
    @classmethod
    def coerce(cls, d: Any) -> Any:
        if not isinstance(d, dict):
            return d
        x = dict(d)
        v = x.get("is_hiring")
        if isinstance(v, str):
            x["is_hiring"] = v.strip().lower() in {"true", "yes", "y", "1", "hiring"}
        x.setdefault("reasoning", "")
        return x


_HIRING_SYSTEM = (
    "You filter LinkedIn posts. Decide ONLY whether the post is a hiring post — i.e. it is offering a "
    "job/role/internship/contract or asking candidates to apply. Ignore whether the role matches any "
    "particular profile; that's a separate decision. Output ONLY the structured schema."
)

_HIRING_HUMAN = """Is this a hiring post?

A hiring post:
- announces an open role / position / vacancy / opportunity / internship / contract,
- OR asks candidates to apply / send CV / send résumé / DM for a role,
- OR contains an "apply at <url>", "send your application to <email>", or "we're hiring" phrasing.

A NON-hiring post (return false):
- celebrating a hire / new job announcement of someone else,
- recruitment-services / CV-writing services / coaching sales pitches,
- team-building / events / hackathons,
- general career advice or thought-leadership,
- promotional content from a recruiter selling services rather than offering a role,
- repost / share with no role attached.

Content:
{content}

Output is_hiring: true|false plus one short sentence of reasoning.
"""


class MatchResult(BaseModel):
    """Stage 2: is this hiring post a fit, and if so how should we contact?"""
    model_config = ConfigDict(extra="ignore")
    compatible: bool = Field(..., description="True if the role broadly fits the candidate's target.")
    match_score: int = Field(..., ge=0, le=100, description="Same 0-100 scale as the legacy job scorer.")
    contact_mode: ContactMode = Field(..., description="EMAIL / LINK / DM / NONE based on what the post itself says.")
    extracted_email: str = Field(default="")
    apply_url: str = Field(default="")
    draft_message: str = Field(default="")
    draft_subject: str = Field(
        default="",
        description=(
            "Email subject line — filled only when contact_mode is EMAIL. "
            "Tailored to the role/title from the post (e.g. "
            "'Application — Junior AI Engineer (Python, LLMs)'). Keep under "
            "80 chars, no quotes, no emoji. Match the language of the post."
        ),
    )
    reasoning: str = Field(default="")

    @model_validator(mode="before")
    @classmethod
    def coerce(cls, d: Any) -> Any:
        if not isinstance(d, dict):
            return d
        x = dict(d)
        v = x.get("compatible")
        if isinstance(v, str):
            x["compatible"] = v.strip().lower() in {"true", "yes", "y", "1", "compatible"}
        cm = x.get("contact_mode")
        if isinstance(cm, str):
            up = cm.strip().upper()
            x["contact_mode"] = up if up in ("EMAIL", "LINK", "DM", "NONE") else "NONE"
        elif cm is None:
            x["contact_mode"] = "NONE"
        for k in ("extracted_email", "apply_url", "draft_message", "draft_subject", "reasoning"):
            if x.get(k) is None:
                x[k] = ""
        if x.get("match_score") is None:
            x["match_score"] = 0
        return x


_MATCH_SYSTEM = (
    "You are matching a confirmed-hiring LinkedIn post to the candidate's profile, and deciding "
    "HOW to reach out based on what the post itself says. Output ONLY the structured schema."
)

_MATCH_HUMAN = """A hiring post has been confirmed. Decide compatibility + how to contact.

Candidate Preferences:
{preferences}

Resume:
{resume}

Hiring post:
{content}

COMPATIBILITY (set `compatible`):
- true if the role's domain or tech stack overlaps with the candidate's target by ANY of:
   * domain match (AI/ML/data/software when candidate is in that space),
   * 1+ tech stack overlap (Python, LLMs, RAG, LangChain, PyTorch, SQL, etc.),
   * generalist-friendly title with no senior bar.
- false ONLY if the role is in a clearly unrelated domain (legal, accounting, mechatronics, pure HR,
  marketing-only, sales-only) AND has NO tech overlap with the resume.
- DO NOT use compatibility==false just because seniority is unclear or years-experience is high.
- BE GENEROUS: when in doubt, return true.

CONTACT MODE (set `contact_mode`) — based on what the post LITERALLY says to do:
- EMAIL — post contains an "@"-style email address OR text like "send your CV to <addr>",
  "envoyez votre CV à <addr>", "contact us at <addr>". Put the address in `extracted_email`.
- LINK  — post says "apply here / apply at / link in bio / use this form / lien dans la bio"
  OR contains an external job/ATS URL (workday, greenhouse, lever, smartrecruiters, taleo,
  bamboohr, ashbyhq, recruitee, /jobs/view/, dropbox/google-form). Put it in `apply_url`.
- DM    — post says "DM me", "message me", "contact me directly", "envoyez-moi un message".
- NONE  — the post is hiring + compatible but gives no contact route. Skip.

DRAFT MESSAGE (only when contact_mode is EMAIL or DM):
- Match the LANGUAGE of the post.
- EMAIL: 120-180 words, complete body (greeting + body + sign-off with candidate name from resume).
  Do NOT include a "Subject:" line inside the body — the subject goes in
  draft_subject. Mention that the CV is attached (since the agent attaches the
  PDF automatically when sending).
- DM: 80-120 words, single message, no markdown.
- Cite the SPECIFIC role/title from the post + 1-2 concrete tech items from the resume.
- No placeholders like [Name] / [Company]. Fill in actual values.

DRAFT SUBJECT (only when contact_mode is EMAIL):
- Short, specific, < 80 chars. No quotes, no emoji, no ALL CAPS.
- Reference the actual role/title from the post (e.g. "Application — Junior
  AI Engineer (Python, LLMs)" or "Candidature — Stage IA / LLMs").
- Match the language of the post.
- If the post mentions a company / lab / team name, include it.

OUTPUT:
- compatible: true | false
- match_score: 0-100 (start 50; +25 domain; +15 stack; +10 junior-friendly; -20 unrelated).
- contact_mode: EMAIL | LINK | DM | NONE
- extracted_email: address if EMAIL else ""
- apply_url: url if LINK else ""
- draft_message: filled if EMAIL or DM, else ""
- draft_subject: filled if EMAIL, else ""
- reasoning: 1-2 sentences.
"""


# ───────────────────────── PROFILE evaluator (Networking) ────────────────────────────────
# Single LLM call that decides fit + drafts a personalized invite/DM. Mirrors the
# POST-mode flow so network_node can send an empty invite and queue this message
# for the sweeper to deliver after acceptance.

class ProfileMatchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    compatible: bool = Field(..., description="True if the profile holder is worth networking with.")
    match_score: int = Field(..., ge=0, le=100)
    draft_message: str = Field(default="", description="Personalized DM body, filled only if compatible.")
    reasoning: str = Field(default="")
    gender_guess: str = Field(
        default="unknown",
        description=(
            "Inferred gender of the profile holder from their first name. One of: "
            "'m' (masculine — Monsieur / Mr), 'f' (feminine — Madame / Ms), "
            "'unknown' (truly ambiguous — Sam, Alex, Robin, …). Be decisive for "
            "names with clear gender association in their culture."
        ),
    )
    contact_category: str = Field(
        default="expert",
        description=(
            "Which outreach template to use. One of: "
            "'hr'     — the profile is an HR / recruiter / talent / hiring-manager / "
            "           sourcer / people-ops role (RULE 1). They are gatekeepers, "
            "           so the message asks directly about opportunities. "
            "'expert' — the profile is a domain professional (engineer, dev, manager, "
            "           founder, etc.) whose field overlaps the candidate's resume "
            "           (RULE 2). They are NOT recruiting, so the message asks for "
            "           advice / orientation instead of pitching directly."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def coerce(cls, d: Any) -> Any:
        if not isinstance(d, dict):
            return d
        x = dict(d)
        v = x.get("compatible")
        if isinstance(v, str):
            x["compatible"] = v.strip().lower() in {"true", "yes", "y", "1", "compatible"}
        for k in ("draft_message", "reasoning"):
            if x.get(k) is None:
                x[k] = ""
        if x.get("match_score") is None:
            x["match_score"] = 0
        g = x.get("gender_guess")
        if isinstance(g, str):
            gl = g.strip().lower()
            if gl in {"m", "male", "man", "masculine", "monsieur", "mr", "mister"}:
                x["gender_guess"] = "m"
            elif gl in {"f", "female", "woman", "feminine", "madame", "mrs", "ms", "miss"}:
                x["gender_guess"] = "f"
            else:
                x["gender_guess"] = "unknown"
        else:
            x["gender_guess"] = "unknown"
        c = x.get("contact_category")
        if isinstance(c, str):
            cl = c.strip().lower()
            if cl in {"hr", "recruiter", "talent", "hiring", "people", "sourcer", "rh"}:
                x["contact_category"] = "hr"
            else:
                x["contact_category"] = "expert"
        else:
            x["contact_category"] = "expert"
        return x


_PROFILE_SYSTEM = (
    "You are deciding whether a LinkedIn profile is worth a networking outreach for the candidate, "
    "and crafting a personalized message to queue for after they accept the connection request. "
    "Output ONLY the structured schema."
)

_PROFILE_HUMAN = """A LinkedIn profile has been scraped. Decide ONLY whether the candidate
should reach out (compatible=true/false). The DM body itself is generated by the calling
code from a fixed template — do NOT write a draft_message. Leave `draft_message` empty.

Candidate Preferences:
{preferences}

Candidate Resume:
{resume}

Profile to evaluate:
{content}

COMPATIBILITY (set `compatible`):
- Use whichever Profile fields are present — Headline, About, Experience, Current role,
  Current company — to judge whether the candidate should reach out. LinkedIn doesn't
  always serve all fields to scrapers, so be flexible: a single strong signal (e.g.
  "Recruiter" in the headline, or "AI Engineer at Google" anywhere) is enough.

- RULE 1 — HR ALWAYS WINS. ANY HR / RECRUITER / TALENT / HIRING role is
  ALWAYS compatible=true, no matter the industry, company, country, or
  seniority. People-function titles include (in any language):
  HR, Human Resources, Talent Acquisition, Recruiter, Recruiting, Sourcer,
  People Operations, HRBP, Hiring Manager, Staffing, Headhunter, Ressources
  Humaines, RH, DRH, RRH, Recruteur, Chargé(e) de recrutement, Recursos
  Humanos, Reclutador, Risorse Umane, Personalwesen, Personalreferent,
  Recrutamento — and any other clear variant. These are the gatekeepers;
  networking with them is always valuable regardless of which company or
  field.

- RULE 2 — CV-FIELD OVERLAP. compatible=true if the profile shows experience
  in ANY field, domain, skill, technology, or role that ALSO appears in the
  candidate's Resume above. Walk the resume and check: any matching job
  title, programming language, framework, library, tool, methodology,
  industry, or academic subject is enough. Do NOT restrict to a single
  "target domain" — the resume is the source of truth. Examples:
   * Resume mentions Python + LangChain + Computer Vision → a "Computer
     Vision Engineer" or a "Python Backend Dev" both qualify.
   * Resume mentions Java/Android → a "Mobile Developer" qualifies.
   * Resume mentions SQL/Snowflake → a "Data Engineer" qualifies.
   * Resume mentions n8n/automation → a "Workflow Automation Consultant"
     qualifies.
  Decision-makers (Director, VP, Head of, CTO, CEO, Founder) in a field
  that touches ANY resume topic also qualify, as do employees at companies
  the candidate explicitly listed as targets.

- compatible=false ONLY when NEITHER rule fires: the profile is not an
  HR/recruiter/hiring role AND has zero overlap with any field, skill, or
  industry on the candidate's resume.

- If EVERY field is empty (only Name was captured), return compatible=false with
  reasoning "[no-data]". Don't guess from the name alone.

- BE GENEROUS — when in doubt, return true. Recruiters/HR ALWAYS win, and
  any single CV-field overlap is enough.

OUTPUT:
- compatible: true | false
- match_score: 0-100 (start 50; +30 HR/recruiter/hiring-manager signal;
  +20 any resume-field overlap (skill/tool/domain/industry); +10 per
  additional overlap up to +20; -20 only when no overlap AND not HR).
- draft_message: ALWAYS empty string. The body is generated downstream from a fixed template.
- reasoning: 1-2 sentences citing matched skills/domain.
- contact_category: 'hr' | 'expert'.
   * 'hr'     — the profile is a recruiter / HR / talent / sourcer / hiring
                manager / people-ops / RH / DRH / staffing role (RULE 1
                fired). These are gatekeepers; they expect candidate pitches.
   * 'expert' — the profile is a domain professional (engineer, developer,
                manager, founder, CTO, researcher, …) whose field overlaps
                the resume (RULE 2 fired) but who is NOT in a recruiting/HR
                role. They are NOT recruiting, so we ask for advice / referral
                instead of pitching directly. DEFAULT to 'expert' when
                uncertain — the HR template only fits actual HR people.
- gender_guess: 'm' | 'f' | 'unknown' — inferred from the FIRST name only (ignore the surname).
  Use cultural context: French/Arabic/English/Spanish/etc. name-gender associations are well
  known. BE DECISIVE — 'unknown' is reserved for truly ambiguous unisex names (Sam, Alex,
  Robin, Andrea-in-Italian, Jamie). Examples to be confident on:
    * Kaoutar, Fatima, Salma, Sophie, Marie, Mariem, Khadija → 'f'
    * Hicham, Mohamed, Yassine, Pierre, Anass, Yahya, Pedro → 'm'
  Pick by the dominant association in the most-likely culture (use the Profile language
  hint to disambiguate cross-cultural names).
"""


# ── Outreach templates (FR / EN only) ────────────────────────────────────────
# The DM body is NOT LLM-generated. It's substituted from these templates with
# the recipient's first name + honorific. Language is chosen by
# `Profile language: fr|en` from extract_profile_details. The honorific is
# chosen by gender_guess from the LLM ('m' → Monsieur/Mr, 'f' → Madame).
# Two languages only — the bot speaks French to francophone-region contacts
# and English to everyone else.

_OUTREACH_TEMPLATE_FR = (
    "Bonjour {honorific} {name},\n"
    "\n"
    "J'ai vu votre profil et je souhaitais savoir s'il y avait des opportunités, "
    "que ce soit pour un stage ou un poste de travail dans le domaine de l'IA. "
    "Si mon profil vous intéresse, je peux vous envoyer mon CV.\n"
    "\n"
    "Merci d'avance pour votre retour."
)

_OUTREACH_TEMPLATE_EN = (
    "Hello {honorific} {name},\n"
    "\n"
    "I came across your profile and wanted to ask if there are any opportunities "
    "available, whether for an internship or a job position in the field of AI. "
    "If my profile interests you, I would be happy to send you my CV.\n"
    "\n"
    "Thank you in advance for your response."
)

# Expert / non-HR templates. The candidate isn't pitching the recipient as a
# hiring gatekeeper — they're asking a domain peer for advice, referrals, or
# direction. Softer tone, no "send me your CV if you're interested".
_OUTREACH_TEMPLATE_FR_EXPERT = (
    "Bonjour {honorific} {name},\n"
    "\n"
    "Je suis tombé sur votre profil et je me permets de vous contacter pour "
    "demander conseil concernant des opportunités dans le domaine de l'IA. "
    "Je suis actuellement à la recherche d'un stage ou d'un emploi, et je "
    "voulais savoir si vous connaissiez des opportunités ou si vous pouviez "
    "m'orienter dans la bonne direction.\n"
    "\n"
    "Si besoin, je serais ravi de vous partager mon CV.\n"
    "\n"
    "Merci d'avance pour votre temps et votre aide."
)

_OUTREACH_TEMPLATE_EN_EXPERT = (
    "Hello {honorific} {name},\n"
    "\n"
    "I came across your profile and wanted to reach out for advice regarding "
    "opportunities in the AI field. I am currently looking for either an "
    "internship or a job, and I was wondering if you might know of any "
    "opportunities or could guide me in the right direction.\n"
    "\n"
    "If needed, I would be happy to share my CV with you.\n"
    "\n"
    "Thank you in advance for your time and help."
)

# Honorific tables. `unknown` falls back to "Madame" — safer in tone than
# defaulting to "Monsieur" (mis-addressing a woman as Mr is worse than the
# reverse in most professional contexts).
_HONORIFICS = {
    "fr": {"m": "Monsieur", "f": "Madame", "unknown": "Madame"},
    "en": {"m": "Mr",       "f": "Madame", "unknown": "Madame"},
}


def _first_name_for_greeting(full_name: str) -> str:
    """Pull a clean first name out of profile.name for the greeting substitution.
    Strips flag emojis, decoration, common titles, then takes the first token.
    Falls back to the raw full name if parsing fails — never returns empty so
    we don't end up with 'Bonjour Madame/Monsieur ,'."""
    import re as _re
    raw = (full_name or "").strip()
    if not raw:
        return "?"
    # Drop emoji (flag clusters + general symbol block).
    cleaned = _re.sub(r"[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF☀-➿]", " ", raw)
    # Drop honorifics if LinkedIn ever surfaces them.
    cleaned = _re.sub(r"^(dr|prof|mr|mrs|ms|mme|m)\.?\s+", "", cleaned.strip(), flags=_re.IGNORECASE)
    cleaned = cleaned.strip()
    if not cleaned:
        return raw.split()[0] if raw.split() else "?"
    first = cleaned.split()[0]
    # Common LinkedIn artifact: names rendered in ALL CAPS (e.g. "FAIZ Kaoutar")
    # come back as the FAMILY name first — keep it as-is, the greeting still
    # reads naturally. We don't try to reorder.
    return first


def _build_outreach_message(
    profile: dict,
    gender: str = "unknown",
    category: str = "hr",
) -> str:
    """Render the standard outreach template in the right language with the
    recipient's first name + a single honorific (Madame OR Monsieur — never
    both).

    Args:
        profile:  dict produced by extract_profile_details — uses `name` and
                  `primary_lang`.
        gender:   'm' / 'f' / 'unknown' — the LLM's inferred gender for the
                  first name. Defaults to 'unknown' which maps to "Madame"
                  (safer fallback than "Monsieur" in professional contexts).
        category: 'hr' (recruiter/HR/talent — pitches opportunities directly)
                  or 'expert' (domain peer — asks for advice / orientation).
    """
    lang = (profile.get("primary_lang") or "en").lower()
    if lang not in ("fr", "en"):
        lang = "en"
    g = (gender or "unknown").lower()
    if g not in ("m", "f", "unknown"):
        g = "unknown"
    cat = (category or "hr").lower()
    if cat not in ("hr", "expert"):
        cat = "hr"
    if cat == "expert":
        template = _OUTREACH_TEMPLATE_FR_EXPERT if lang == "fr" else _OUTREACH_TEMPLATE_EN_EXPERT
    else:
        template = _OUTREACH_TEMPLATE_FR if lang == "fr" else _OUTREACH_TEMPLATE_EN
    honorific = _HONORIFICS[lang][g]
    return template.format(
        honorific=honorific,
        name=_first_name_for_greeting(profile.get("name") or ""),
    )


# Markers that indicate the role is an internship (regardless of language).
# Used to skip profiles whose MOST RECENT experience is an internship —
# interns aren't hiring gatekeepers and can't refer the candidate, so even an
# HR or skill-overlap match isn't actionable. Matched on word boundaries to
# avoid false positives like "internal", "international", "interim".
_INTERN_WORD_PATTERNS = (
    r"\bintern\b",            # EN: "ML Engineer Intern"
    r"\binternship\b",        # EN: "· Internship" employment-type tag
    r"\btrainee\b",           # EN
    r"\bapprentice\b",        # EN
    r"\bapprenticeship\b",    # EN
    r"\bstagiaire\b",         # FR
    r"\bstage\b",             # FR (employment-type tag)
    r"\balternance\b",        # FR (alternance / work-study)
    r"\bapprenti(?:e)?\b",    # FR
    r"\bbecari[oa]\b",        # ES
    r"\bprácticas\b",         # ES
    r"\bpasantía\b",          # ES (LatAm)
    r"\bpasante\b",           # ES (LatAm)
    r"\btirocinante\b",       # IT
    r"\bstagista\b",          # IT
    r"\btirocinio\b",         # IT
    r"\bestagiári[oa]\b",     # PT
    r"\bestágio\b",           # PT
    r"\bpraktikant(?:in)?\b", # DE
    r"\bpraktikum\b",         # DE
    r"\bauszubildende[r]?\b", # DE (apprentice)
)


def _looks_like_intern(text: str) -> bool:
    """True iff `text` looks like an internship/trainee/apprentice role.

    Used to filter out profiles whose latest experience is just an internship:
    those people are peers, not gatekeepers, so reaching out has no expected
    value. Multi-locale on purpose — LinkedIn renders the employment-type tag
    in the profile's display language, so EN, FR, ES, IT, PT, DE all need to
    fire."""
    if not text:
        return False
    import re as _re
    low = text.lower()
    return any(_re.search(p, low) for p in _INTERN_WORD_PATTERNS)


def _eval_profile(state: AgentState, content: str, model_name: str) -> dict:
    # ── Pre-filter: skip profiles whose LATEST experience is an internship. ──
    # We check both the parsed `current_role` (e.g. "ML Engineer Intern") AND
    # the head of the Experience text (covers the "· Internship" / "· Stage"
    # employment-type tag LinkedIn renders on the company line — that tag is
    # the clearest "this is an intern role" signal but doesn't land in
    # current_role, which is just the title line). 240 chars is enough to
    # cover both lines of the first experience block without bleeding into
    # the second.
    profile = state.get("profile_details") or {}
    current_role = (profile.get("current_role") or "").strip()
    experience_head = (profile.get("experience") or "")[:240]
    if _looks_like_intern(current_role) or _looks_like_intern(experience_head):
        return {
            "match_score": 0,
            "reasoning": (
                f"[intern-only] Latest experience appears to be an internship "
                f"(role={current_role!r}); skipping — interns can't refer or "
                "hire."
            ),
            "action_taken": "SKIP",
            "extracted_email": "",
            "apply_url": "",
            "draft_message": "",
        }

    llm = _get_llm(model_name)
    resume_text = get_resume_text()
    preferences = (
        f"- Target Role: {state.get('search_role', 'Any')}\n"
        f"- Target Locations: {', '.join(state.get('search_locations', ['Worldwide']))}\n"
        f"- Target Company: {state.get('target_company', '') or 'Any'}\n"
    )
    chain = (
        ChatPromptTemplate.from_messages([("system", _PROFILE_SYSTEM), ("human", _PROFILE_HUMAN)])
        | llm.with_structured_output(ProfileMatchResult, method="json_schema")
    )
    match, exc = _call_with_retry(chain, {
        "content": content,
        "resume": resume_text,
        "preferences": preferences,
    })
    if exc is not None or match is None:
        return {
            "match_score": 0,
            "reasoning": f"Profile LLM failed: {exc}",
            "action_taken": "SKIP",
            "extracted_email": "",
            "apply_url": "",
            "draft_message": "",
            "errors": state.get("errors", []) + [f"profile-llm: {exc}"],
        }
    if not match.compatible:
        return {
            "match_score": match.match_score,
            "reasoning": f"[profile-no-fit] {match.reasoning}",
            "action_taken": "SKIP",
            "extracted_email": "",
            "apply_url": "",
            "draft_message": "",
        }
    # DM body is template-driven, NOT LLM-generated. Pick FR/EN from the
    # primary_lang field, substitute the recipient's first name + honorific
    # (Madame / Monsieur — never both). The LLM only decides compatibility/
    # score/reasoning + infers gender from the first name; draft_message
    # comes from us.
    profile = state.get("profile_details") or {}
    return {
        "match_score": match.match_score,
        "reasoning": (
            f"[profile-match] {match.reasoning} "
            f"[gender={match.gender_guess}] [category={match.contact_category}]"
        ),
        "action_taken": "NETWORK",
        "extracted_email": "",
        "apply_url": "",
        "draft_message": _build_outreach_message(
            profile,
            gender=match.gender_guess,
            category=match.contact_category,
        ),
    }


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
        return _format_profile_for_llm(state["profile_details"])
    if state.get("post_details"):
        return f"POST DETAILS:\n{state['post_details']}"
    return ""


def _format_profile_for_llm(profile: dict) -> str:
    """Render whatever profile data the scraper managed to extract — as labeled
    fields. The LLM gets EVERY available signal (headline, about, experience,
    current_role, current_company, language) so it can decide compatibility
    flexibly: if Experience is empty (LinkedIn often serves the bot a degraded
    profile view), it can still fall back to Headline + About to figure out
    what the person does.

    No field is hardcoded as required or excluded; whichever fields are
    populated, the LLM gets. Empty fields are omitted to keep the prompt
    short and to not mislead the LLM into thinking we know things we don't."""
    lines = ["PROFILE DETAILS:"]

    name = (profile.get("name") or "").strip()
    if name:
        lines.append(f"Name: {name}")

    primary_lang = (profile.get("primary_lang") or "").strip()
    if primary_lang:
        lines.append(f"Profile language: {primary_lang}")

    current_role = (profile.get("current_role") or "").strip()
    if current_role:
        lines.append(f"Current role: {current_role}")

    current_company = (profile.get("current_company") or "").strip()
    if current_company:
        lines.append(f"Current company: {current_company}")

    headline = (profile.get("headline") or "").strip()
    if headline:
        lines.append(f"Headline: {headline}")

    # About re-included: when Experience extraction fails (degraded LinkedIn
    # view), About is often the only place that mentions what the person
    # actually does. Capping at 1500 chars to avoid bloating the prompt.
    about = (profile.get("about") or "").strip()
    if about:
        lines.append(f"About:\n{about[:1500]}")

    experience = (profile.get("experience") or "").strip()
    if experience:
        lines.append(f"Experience:\n{experience[:3500]}")

    return "\n".join(lines)


def _call_with_retry(chain, payload: dict, retries: int = 3):
    last_exc: Exception | None = None
    for _ in range(retries):
        try:
            return chain.invoke(payload), None
        except Exception as exc:
            last_exc = exc
    return None, last_exc


# Broadened to also match the JSON-key form `"is_hiring": true` (an optional
# quote may sit between `hiring` and the colon) and `is-hiring`/`is hiring`.
_HIRING_BOOL_RE = re.compile(
    r'["\']?is[_\s-]?hiring["\']?\s*[:=]\s*["\']?(true|false|yes|no)\b', re.IGNORECASE
)
# Accept both "Reason:" and "reasoning:" (the model uses either).
_HIRING_REASON_RE = re.compile(
    r'reason(?:ing)?["\']?\s*[:=]\s*["\']?(.+?)["\']?\s*(?:\n\s*\n|\Z)',
    re.IGNORECASE | re.DOTALL,
)
# LangChain appends this to OUTPUT_PARSING_FAILURE messages; strip it from any
# reasoning we salvage out of an exception string.
_TROUBLESHOOT_TAIL_RE = re.compile(r"\s*For troubleshooting.*$", re.IGNORECASE | re.DOTALL)


def _parse_hiring_text(text: str) -> HiringCheck | None:
    """Extract a HiringCheck from arbitrary model text (or from the raw output
    embedded in a LangChain parser-exception string). Tries an embedded JSON
    object first, then loose ``is_hiring: <bool>`` / ``Reason: ...`` extraction.

    Returns None only when no hiring verdict can be found at all."""
    if not text:
        return None
    # 1. Any embedded JSON object that carries the verdict.
    for m in re.finditer(r"\{[^{}]*\}", text, re.DOTALL):
        try:
            d = json.loads(m.group(0))
        except Exception:
            continue
        if isinstance(d, dict) and "is_hiring" in d:
            try:
                return HiringCheck(**d)  # coerce validator handles str→bool
            except Exception:
                pass
    # 2. Loose key:value extraction.
    bm = _HIRING_BOOL_RE.search(text)
    if not bm:
        return None
    is_hiring = bm.group(1).lower() in {"true", "yes"}
    rm = _HIRING_REASON_RE.search(text)
    reasoning = (rm.group(1).strip() if rm else text.strip())[:300]
    reasoning = _TROUBLESHOOT_TAIL_RE.sub("", reasoning).strip()
    return HiringCheck(is_hiring=is_hiring, reasoning=reasoning)


def _hiring_from_raw_text(llm, content: str) -> HiringCheck | None:
    """Last-resort fallback: re-ask the model WITHOUT structured output and parse
    the plain-text reply. Only used after salvaging the first reply's text failed
    — Ollama models intermittently answer in prose instead of strict JSON."""
    try:
        raw = llm.invoke([
            ("system", _HIRING_SYSTEM),
            ("human", _HIRING_HUMAN.format(content=content)),
        ])
    except Exception:
        return None
    text = getattr(raw, "content", None) or str(raw) or ""
    return _parse_hiring_text(text)


def _eval_post(state: AgentState, content: str, model_name: str) -> dict:
    """Two LLM calls: classify hiring vs not, then (if hiring) match + contact mode."""
    llm = _get_llm(model_name)
    resume_text = get_resume_text()
    preferences = (
        f"- Target Role: {state.get('search_role', 'Any')}\n"
        f"- Target Locations: {', '.join(state.get('search_locations', ['Worldwide']))}\n"
        f"- Workplace Types: {', '.join(state.get('workplace_types', ['Remote', 'Hybrid', 'On-site']))}\n"
    )

    # ── Stage A: hiring classifier ──
    hiring_chain = (
        ChatPromptTemplate.from_messages([("system", _HIRING_SYSTEM), ("human", _HIRING_HUMAN)])
        | llm.with_structured_output(HiringCheck, method="json_schema")
    )
    hiring, exc = _call_with_retry(hiring_chain, {"content": content})
    if exc is not None or hiring is None:
        # The model's actual reply is embedded in the parser exception
        # ("Invalid json output: is_hiring: true Reason: ..."). Salvage it
        # directly before paying for a second LLM call.
        hiring = _parse_hiring_text(str(exc)) or _hiring_from_raw_text(llm, content)
        if hiring is None:
            return {
                "match_score": 0,
                "reasoning": f"Hiring-classifier LLM failed: {exc}",
                "action_taken": "SKIP",
                "extracted_email": "",
                "apply_url": "",
                "draft_message": "",
                "errors": state.get("errors", []) + [f"hiring-llm: {exc}"],
            }
    if not hiring.is_hiring:
        return {
            "match_score": 0,
            "reasoning": f"[non-hiring] {hiring.reasoning}",
            "action_taken": "SKIP",
            "extracted_email": "",
            "apply_url": "",
            "draft_message": "",
        }

    # ── Stage B: match + contact mode ──
    match_chain = (
        ChatPromptTemplate.from_messages([("system", _MATCH_SYSTEM), ("human", _MATCH_HUMAN)])
        | llm.with_structured_output(MatchResult, method="json_schema")
    )
    match, exc = _call_with_retry(match_chain, {
        "content": content,
        "resume": resume_text,
        "preferences": preferences,
    })
    if exc is not None or match is None:
        return {
            "match_score": 0,
            "reasoning": f"Match LLM failed: {exc}",
            "action_taken": "SKIP",
            "extracted_email": "",
            "apply_url": "",
            "draft_message": "",
            "errors": state.get("errors", []) + [f"match-llm: {exc}"],
        }

    if not match.compatible:
        return {
            "match_score": match.match_score,
            "reasoning": f"[hiring-no-fit] {match.reasoning}",
            "action_taken": "SKIP",
            "extracted_email": "",
            "apply_url": "",
            "draft_message": "",
        }

    # Compatible hiring post — pick action from contact_mode.
    post = state.get("post_details") or {}
    email = match.extracted_email or post.get("primary_email") or ""
    apply_url = match.apply_url or post.get("attached_job_url") or ""
    if match.contact_mode == "EMAIL" and email:
        action = "DRAFT_EMAIL"
    elif match.contact_mode == "LINK" and apply_url:
        action = "EXTERNAL_LINK"
    elif match.contact_mode == "DM":
        action = "DRAFT_DM"
    else:
        # Compatible but the post offers no clear contact path. Fall back: if we
        # found an email anywhere in the body, draft; otherwise DM.
        if email:
            action = "DRAFT_EMAIL"
        elif apply_url:
            action = "EXTERNAL_LINK"
        else:
            action = "DRAFT_DM"

    return {
        "match_score": match.match_score,
        "reasoning": f"[{match.contact_mode}] {match.reasoning}",
        "action_taken": action,
        "extracted_email": email,
        "apply_url": apply_url,
        "draft_message": match.draft_message,
        "draft_subject": (match.draft_subject or "").strip(),
    }


def evaluate_node(state: AgentState) -> dict:
    content = _build_content(state)
    if not content:
        return {
            "match_score": 0,
            "reasoning": "No content to evaluate.",
            "action_taken": "SKIP",
            "extracted_email": "",
            "apply_url": "",
            "draft_message": "",
        }

    model_name = resolve_model(state.get("llm_model"))

    # ── POST path: two-stage classifier ──
    if state.get("post_details"):
        return _eval_post(state, content, model_name)

    # ── PROFILE path: dedicated evaluator that drafts a personalized DM ──
    if state.get("profile_details"):
        return _eval_profile(state, content, model_name)

    # ── JOB path: legacy single-call scorer ──
    resume_text = get_resume_text()
    llm = _get_llm(model_name)
    chain = (
        ChatPromptTemplate.from_messages([("system", _EVAL_SYSTEM), ("human", _EVAL_HUMAN)])
        | llm.with_structured_output(EvaluationResult, method="json_schema")
    )
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

    result, exc = _call_with_retry(chain, payload, retries=3)
    if exc is not None or result is None:
        message = f"LLM evaluation failed after retries: {exc}"
        return {
            "match_score": 0,
            "reasoning": message,
            "action_taken": "SKIP",
            "extracted_email": "",
            "apply_url": "",
            "draft_message": "",
            "errors": state.get("errors", []) + [message],
        }

    action = result.action
    reasoning = result.reasoning
    if is_job:
        # Posts can NEVER produce APPLY; jobs respect the threshold.
        if result.match_score >= APPLY_THRESHOLD and action != "APPLY":
            reasoning = f"[forced APPLY: score {result.match_score} >= {APPLY_THRESHOLD}] {reasoning}"
            action = "APPLY"
        elif result.match_score < APPLY_THRESHOLD and action == "APPLY":
            reasoning = f"[forced SKIP: score {result.match_score} < {APPLY_THRESHOLD}] {reasoning}"
            action = "SKIP"

    return {
        "match_score": result.match_score,
        "reasoning": reasoning,
        "action_taken": action,
        "extracted_email": result.extracted_email,
        "apply_url": result.apply_url,
        "draft_message": result.draft_message,
    }
