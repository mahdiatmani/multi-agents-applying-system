from typing import TypedDict, List

class AgentState(TypedDict, total=False):
    search_type: str  # 'JOB', 'PERSON', or 'POST'
    headless: bool
    llm_model: str
    search_role: str
    search_locations: List[str]
    workplace_types: List[str]
    target_company: str

    current_url: str
    job_details: dict
    profile_details: dict
    post_details: dict
    match_score: int
    reasoning: str
    extracted_email: str
    draft_message: str
    action_taken: str
    errors: List[str]

    iterations: int
    empty_streak: int
    max_iterations: int
    resume_path: str
    job_page_start: int
    dry_run: bool
    verbose: bool
