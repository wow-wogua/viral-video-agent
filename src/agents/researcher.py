import json
from langchain_core.messages import HumanMessage
from src.agents.supervisor import get_llm, extract_text
from src.graph.state import AgentState
from src.mcp.client import call_tool
from src.utils.fallback_counter import fallback_counter
from src.utils.trace_tracker import trace_tracker
from src.prompts.manager import prompt_manager

# MCP Client 配置
MCP_SERVER_URL = "http://localhost:8001/sse"


async def call_tool_via_mcp(tool_name: str, params: dict):
    """通过 MCP Client 调用工具，失败时回退到直接调用。"""
    try:
        from mcp.client.session import ClientSession
        from mcp.client.sse import sse_client

        async with sse_client(MCP_SERVER_URL) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, params)
                return result
    except Exception as e:
        print(f"[Researcher] MCP调用失败，回退到直接调用: {e}")
        return await call_tool(tool_name, params)


async def researcher_node(state: AgentState) -> dict:
    trace_tracker.start_agent("researcher")
    llm = get_llm("researcher")
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)
    platforms = state.get("platforms") or ["bilibili"]

    if current_step >= len(plan):
        trace_tracker.end_agent("researcher")
        return {"data_sufficient": True}

    task = plan[current_step]
    print(f"[Researcher] exec: {task}")

    prompt = prompt_manager.get("researcher", task=task, platforms=platforms)

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    text = extract_text(response)

    # 解析LLM输出，兜底到硬编码
    tool_name = "search_videos"
    params = {"keyword": task, "platforms": platforms, "limit": 5}
    try:
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        decision = json.loads(clean)
        tool_name = decision.get("tool", "search_videos")
        params = decision.get("params", params)
        if tool_name == "search_videos" and not params.get("platforms"):
            params["platforms"] = platforms
        fallback_counter.log("researcher", "json")
        print(f"[Researcher] LLM选择工具: {tool_name}")
    except (json.JSONDecodeError, KeyError) as e:
        fallback_counter.log("researcher", "default")
        print(f"[Researcher] LLM输出解析失败，使用默认: {e}")

    raw_data = await call_tool_via_mcp(tool_name, params)

    trace_tracker.end_agent("researcher")
    return {
        "raw_data": raw_data,
        "search_queries_used": [task],
        "data_sufficient": len(raw_data) > 0,
        "current_step": current_step + 1,
    }
