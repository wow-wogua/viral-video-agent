import json
import re
from langchain_core.messages import HumanMessage
from src.graph.constants import PLANNER, RESEARCHER, ANALYST, WRITER
from src.gateway.llm_router import get_llm
from src.memory.long_term import recall_memory
from src.utils.fallback_counter import fallback_counter
from src.utils.trace_tracker import trace_tracker
from src.prompts.manager import prompt_manager
from src.config import ANALYSIS_CONFIDENCE_THRESHOLD, ANALYST_MAX_ITERATIONS

MAX_SUPERVISOR_ROUNDS = 20

INTENT_CLASSIFY_PROMPT = """你是一个意图分类器。判断用户请求是否需要"短视频爆款分析"。

用户请求: {request}

如果用户请求是关于以下内容，返回 "analyze"：
- 分析视频/短视频/爆款
- 搜索/查找视频数据
- 生成视频分析报告
- B站/抖音等平台数据分析

其他所有请求返回 "chat"，包括：
- 闲聊、问候
- 一般知识问答
- 创意建议（如标题建议、选题建议）
- 和视频分析无关的任何请求

只返回 "analyze" 或 "chat"，不要返回其他内容。"""

DIRECT_ANSWER_PROMPT = """你是一个友好的AI助手。请直接回答用户的问题，简洁明了。

用户问题: {request}

直接回答："""


async def _classify_intent(user_request: str) -> str:
    """分类用户意图：analyze（走Agent流程）或 chat（直接回答）。"""
    try:
        llm = get_llm()
        prompt = INTENT_CLASSIFY_PROMPT.format(request=user_request)
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        text = extract_text(response).strip().lower()
        if "analyze" in text:
            return "analyze"
        return "chat"
    except Exception as e:
        print(f"[Supervisor] 意图分类失败，默认走分析流程: {e}")
        return "analyze"


async def _direct_answer(user_request: str) -> str:
    """对于非分析请求，直接用 LLM 回答。"""
    try:
        llm = get_llm()
        prompt = DIRECT_ANSWER_PROMPT.format(request=user_request)
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return extract_text(response)
    except Exception as e:
        return f"抱歉，处理您的请求时出现错误: {e}"


def extract_text(response) -> str:
    """从 LLM 响应中提取文本，同时记录 token 消耗。MiMo 返回 list[dict]，Claude 返回 str。"""
    # 记录 LLM 调用次数（自动关联当前 Agent）
    trace_tracker.log_llm_call()

    # 从响应中提取 token 使用量（不依赖回调，更可靠）
    try:
        usage = response.usage_metadata
        if usage:
            from src.gateway.cost_tracker import cost_tracker
            cost_tracker.log_usage(
                "agent", "model",
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
            )
    except Exception:
        pass

    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # 优先取 text block
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "").strip()
                if text:
                    return text
        # 没有 text block → MiMo 只返回了 thinking，返回空让调用方重试
        return ""
    return str(content)


async def supervisor_node(state: dict) -> dict:
    trace_tracker.start_agent("supervisor")
    rounds = state.get("supervisor_rounds", 0) + 1

    # 第一轮：意图分类 + 记忆召回
    if rounds == 1:
        # 意图分类：判断是否需要走完整 Agent 流程
        user_request = state.get("user_request", "")
        intent = await _classify_intent(user_request)
        if intent == "chat":
            print(f"[Supervisor] 意图分类: chat，直接回答，不走 Agent 流程")
            direct_answer = await _direct_answer(user_request)
            trace_tracker.end_agent("supervisor")
            return {"next_agent": "end", "supervisor_rounds": rounds, "report_final": direct_answer, "task_complete": True}

        # 召回用户历史偏好
        try:
            memories = await recall_memory("default", state.get("user_request", ""))
            if memories:
                state["long_term_memories"] = memories
                print(f"[Supervisor] 召回 {len(memories)} 条用户偏好")
        except Exception as e:
            print(f"[Supervisor] 记忆召回失败: {e}")

    # 最大轮数强制结束
    if rounds > MAX_SUPERVISOR_ROUNDS:
        print(f"[Supervisor] 达到最大轮数 {MAX_SUPERVISOR_ROUNDS}，强制结束")
        trace_tracker.end_agent("supervisor")
        return {"next_agent": "end", "supervisor_rounds": rounds}

    # 快速检查：任务已完成
    if state.get("task_complete"):
        trace_tracker.end_agent("supervisor")
        return {"next_agent": "end", "supervisor_rounds": rounds}

    # 所有字段都齐全
    if state.get("plan") and state.get("data_sufficient") and state.get("analysis") and state.get("report_final"):
        trace_tracker.end_agent("supervisor")
        return {"next_agent": "end", "supervisor_rounds": rounds}

    # 确定性自评回环：分析置信度低于阈值时继续 Analyst，避免只依赖 LLM 路由 Prompt。
    if state.get("analysis") and not state.get("report_final"):
        confidence = state.get("analysis_confidence", 0.0)
        iterations = state.get("analysis_iterations", 0)
        if confidence < ANALYSIS_CONFIDENCE_THRESHOLD and iterations < ANALYST_MAX_ITERATIONS:
            trace_tracker.end_agent("supervisor")
            return {"next_agent": ANALYST, "supervisor_rounds": rounds}

    llm = get_llm()

    prompt = prompt_manager.get(
        "supervisor",
        has_plan=bool(state.get("plan")),
        data_sufficient=state.get("data_sufficient", False),
        has_analysis=bool(state.get("analysis")),
        analysis_confidence=state.get("analysis_confidence", 0),
        has_report=bool(state.get("report_final")),
        task_complete=state.get("task_complete", False),
    )

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    text = extract_text(response)
    print(f"[Supervisor] 第{rounds}轮决策: {text[:100]}...")

    next_agent = _parse_next_agent(text, state)
    trace_tracker.end_agent("supervisor")
    return {"next_agent": next_agent, "supervisor_rounds": rounds}


def _parse_next_agent(text: str, state: dict) -> str:
    """从 LLM 响应中解析 next 字段，兼容多种格式。"""
    # 1. 去掉 markdown 代码块
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    # 2. 直接解析 JSON
    try:
        decision = json.loads(clean)
        next_val = decision.get("next", "")
        if next_val in {PLANNER, RESEARCHER, ANALYST, WRITER, "end"}:
            fallback_counter.log("supervisor", "json")
            return next_val
    except json.JSONDecodeError:
        pass

    # 3. 用正则从文本中提取 "next": "xxx"
    match = re.search(r'"next"\s*:\s*"(\w+)"', text)
    if match:
        next_val = match.group(1)
        if next_val in {PLANNER, RESEARCHER, ANALYST, WRITER, "end"}:
            fallback_counter.log("supervisor", "regex")
            return next_val

    # 4. 兜底：根据状态推断
    fallback_counter.log("supervisor", "inference")
    if not state.get("report_final"):
        return WRITER
    return "end"


def route_supervisor(state: dict) -> str:
    """读取 LLM 决策的 next_agent 字段进行路由。"""
    next_agent = state.get("next_agent", "end")
    valid = {PLANNER, RESEARCHER, ANALYST, WRITER, "end"}
    if next_agent not in valid:
        return "end"
    return next_agent
