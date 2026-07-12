from langgraph.graph import StateGraph, START, END
from src.graph.state import AgentState
from src.graph.constants import SUPERVISOR, PLANNER, RESEARCHER, ANALYST, WRITER
from src.agents.supervisor import supervisor_node, route_supervisor
from src.agents.planner import planner_node
from src.agents.researcher import researcher_node
from src.agents.analyst import analyst_node
from src.agents.writer import writer_node
from src.memory.short_term import get_checkpointer
from src.config import GRAPH_VERSION


def build_graph(version: str | None = None):
    selected_version = (version or GRAPH_VERSION).lower()
    if selected_version == "v2":
        from src.graph.v2 import build_graph_v2

        return build_graph_v2()
    if selected_version != "v1":
        raise ValueError(f"unsupported graph version: {selected_version}")

    graph = StateGraph(AgentState)

    graph.add_node(SUPERVISOR, supervisor_node)
    graph.add_node(PLANNER, planner_node)
    graph.add_node(RESEARCHER, researcher_node)
    graph.add_node(ANALYST, analyst_node)
    graph.add_node(WRITER, writer_node)

    graph.add_edge(START, SUPERVISOR)

    graph.add_conditional_edges(
        SUPERVISOR,
        route_supervisor,
        {
            PLANNER: PLANNER,
            RESEARCHER: RESEARCHER,
            ANALYST: ANALYST,
            WRITER: WRITER,
            "end": END,
        },
    )

    graph.add_edge(PLANNER, SUPERVISOR)
    graph.add_edge(RESEARCHER, SUPERVISOR)
    graph.add_edge(ANALYST, SUPERVISOR)
    graph.add_edge(WRITER, SUPERVISOR)

    checkpointer = get_checkpointer()
    return graph.compile(checkpointer=checkpointer)
