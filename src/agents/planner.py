from langchain_core.messages import HumanMessage
from src.agents.supervisor import get_llm, extract_text
from src.graph.state import AgentState
from src.prompts.manager import prompt_manager
from src.utils.trace_tracker import trace_tracker


async def planner_node(state: AgentState) -> dict:
    trace_tracker.start_agent("planner")
    llm = get_llm()
    user_request = state.get("user_request", "")

    prompt = prompt_manager.get("planner", user_request=user_request)

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    text = extract_text(response)
    print(f"[Planner] 计划: {text}")

    plan_steps = [
        line.strip()
        for line in text.strip().split("\n")
        if line.strip() and line.strip()[0].isdigit()
    ]
    if not plan_steps:
        plan_steps = [f"1. 分析用户需求并采集相关数据 — 需要: researcher — 预期产出: 数据（{user_request}）"]

    trace_tracker.end_agent("planner")
    return {"plan": plan_steps, "current_step": 0}
