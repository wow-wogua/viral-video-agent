from typing import TypedDict, Annotated
from langgraph.graph import add_messages


class AgentState(TypedDict, total=False):
    user_request: str
    next_agent: str
    task_complete: bool
    plan: list[str]
    current_step: int
    raw_data: list[dict]
    search_queries_used: list[str]
    data_sufficient: bool
    analysis: dict
    analysis_confidence: float
    analysis_iterations: int
    report_draft: str
    report_final: str
    report_revision_count: int
    supervisor_rounds: int
    rag_context: list[str]
    long_term_memories: list[str]
    messages: Annotated[list, add_messages]