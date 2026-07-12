import json
import re
from langchain_core.messages import HumanMessage
from src.agents.supervisor import get_llm, extract_text
from src.graph.state import AgentState
from src.config import ANALYST_MAX_ITERATIONS, V2_ANALYST_MAX_ITERATIONS
from src.utils.fallback_counter import fallback_counter
from src.utils.trace_tracker import trace_tracker
from src.prompts.manager import prompt_manager


async def analyst_node(state: AgentState) -> dict:
    trace_tracker.start_agent("analyst")
    llm = get_llm("analyst")
    raw_data = state.get("raw_data", [])
    prev_analysis = state.get("analysis", {})
    iterations = state.get("analysis_iterations", 0)
    max_iterations = (
        V2_ANALYST_MAX_ITERATIONS
        if state.get("workflow_version") == "v2"
        else ANALYST_MAX_ITERATIONS
    )

    if iterations >= max_iterations:
        confidence = state.get("analysis_confidence", 0.0)
        trace_tracker.end_agent("analyst")
        return {"analysis_confidence": confidence}

    extra = "Previous analysis: " + str(prev_analysis) + " Please improve." if prev_analysis else ""
    user_request = state.get("user_request", "")

    prompt = prompt_manager.get("analyst", raw_data=raw_data, extra=extra, user_request=user_request)

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    text = extract_text(response)
    print(f"[Analyst] round {iterations + 1} done")

    # 尝试解析 JSON
    result = _parse_analysis(text)

    trace_tracker.end_agent("analyst")
    return {
        "analysis": result,
        "analysis_confidence": result.get("confidence", 0.7),
        "analysis_iterations": iterations + 1,
    }


def _parse_analysis(text: str) -> dict:
    """从 LLM 响应中解析分析结果，兼容多种格式。"""
    # 1. 直接解析 JSON
    try:
        result = json.loads(text.strip())
        fallback_counter.log("analyst", "json")
        return result
    except json.JSONDecodeError:
        pass

    # 2. 去掉 markdown 代码块后解析
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        result = json.loads(clean)
        fallback_counter.log("analyst", "json")
        return result
    except json.JSONDecodeError:
        pass

    # 3. 用正则提取 confidence 数值
    fallback_counter.log("analyst", "regex")
    confidence = 0.7
    match = re.search(r'"confidence"\s*:\s*([\d.]+)', text)
    if match:
        confidence = float(match.group(1))

    # 4. 提取 insights 列表
    insights = []
    insight_match = re.search(r'"insights"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if insight_match:
        insights = [s.strip().strip('"') for s in insight_match.group(1).split(",")]

    return {
        "summary": text[:500],
        "insights": insights,
        "confidence": confidence,
    }
