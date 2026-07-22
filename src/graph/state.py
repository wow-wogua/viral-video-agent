from operator import add
from typing import TypedDict, Annotated
from langgraph.graph import add_messages


class AgentState(TypedDict, total=False):
    user_id: str
    user_request: str
    platforms: list[str]
    topic_spec: dict
    workflow_version: str
    next_agent: str
    task_complete: bool
    plan: list[str]
    current_step: int
    raw_data: Annotated[list, add]
    research_tasks: list[dict]
    tool_results: Annotated[list[dict], add]
    evidence: Annotated[list[dict], add]
    available_capabilities: list[dict]
    search_queries_used: Annotated[list[str], add]
    data_sufficient: bool
    analysis: dict
    analysis_confidence: float
    analysis_iterations: int
    report_draft: str
    report_final: str
    report_revision_count: int
    supervisor_rounds: int
    termination_reason: str
    rag_context: list[str]
    long_term_memories: list[str]
    messages: Annotated[list, add_messages]
