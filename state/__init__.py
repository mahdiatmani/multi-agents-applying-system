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
    apply_url: str
    draft_message: str
    draft_subject: str
    action_taken: str
    errors: List[str]

    iterations: int
    empty_streak: int
    max_iterations: int
    resume_path: str
    job_page_start: int
    dry_run: bool
    verbose: bool

    # Batch-scraping state for POST mode: search_post_node scrolls the feed once,
    # scrapes all visible posts, and queues them here. Each iteration pops one for
    # the evaluate node so posts are evaluated one-by-one without re-scraping.
    posts_queue: List[dict]
    posts_batch_role: str
