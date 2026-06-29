from langchain_core.messages import HumanMessage
from src.agents.supervisor import get_llm, extract_text
from src.graph.state import AgentState
from src.config import WRITER_MAX_REVISIONS
from src.memory.long_term import save_memory
from src.prompts.manager import prompt_manager
from src.utils.trace_tracker import trace_tracker


def _extract_topic(user_request: str) -> str:
    """从用户请求中提取主题关键词。"""
    topics = ["音乐", "美食", "游戏", "科技", "舞蹈", "搞笑", "知识", "美妆", "影视", "动画", "体育", "生活"]
    for t in topics:
        if t in user_request:
            return t
    return "短视频"


async def writer_node(state: AgentState) -> dict:
    trace_tracker.start_agent("writer")
    llm = get_llm()
    analysis = state.get("analysis", {})
    raw_data = state.get("raw_data", [])
    draft = state.get("report_draft", "")
    revisions = state.get("report_revision_count", 0)

    if draft and revisions >= WRITER_MAX_REVISIONS:
        # 存储分析记忆
        try:
            user_request = state.get("user_request", "")
            await save_memory("default", "last_analysis", user_request)
            await save_memory("default", "last_report_summary", draft[:200])
            print(f"[Writer] 已存储分析记忆")
        except Exception as e:
            print(f"[Writer] 记忆存储失败: {e}")
        trace_tracker.end_agent("writer")
        return {"report_final": draft, "task_complete": True}

    user_request = state.get("user_request", "")
    topic = _extract_topic(user_request)

    if draft:
        prompt = prompt_manager.get("writer_revision", draft=draft)
    else:
        prompt = prompt_manager.get("writer_draft", analysis=analysis, raw_data=raw_data, user_request=user_request, topic=topic)

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    text = extract_text(response)

    # extract_text 返回空 = MiMo 只输出了 thinking block，重试一次
    if not text:
        print(f"[Writer] MiMo 只返回 thinking，重试...")
        retry_prompt = prompt + "\n\n你的输出必须以 # 开头。不要思考，直接写报告。"
        response = await llm.ainvoke([HumanMessage(content=retry_prompt)])
        text = extract_text(response)

    # 仍为空则从 thinking 内容中提取报告（跳过前面的思考过程）
    if not text:
        content = response.content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    raw = block.get("thinking", "")
                    # 找到第一个 # 标题，从那里开始截取
                    idx = raw.find("\n#")
                    if idx == -1:
                        idx = raw.find("# ")
                    text = raw[idx:].strip() if idx >= 0 else raw
                    break
        text = text or str(content)

    label = "revise" if draft else "draft"
    print(f"[Writer] {label} done, round {revisions + 1}")

    trace_tracker.end_agent("writer")
    return {
        "report_draft": text,
        "report_revision_count": revisions + 1,
    }
