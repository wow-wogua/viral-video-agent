"""
Agent 执行轨迹追踪器
====================
记录每个 Agent 的执行时间、LLM 调用次数、兜底触发次数。

用法:
    from src.utils.trace_tracker import trace_tracker

    trace_tracker.start_agent("supervisor")
    # ... agent 执行 ...
    trace_tracker.end_agent("supervisor")

    trace_tracker.log_llm_call("supervisor")  # 在 LLM 调用时记录

    summary = trace_tracker.get_summary()
"""

import time
from contextvars import ContextVar

# 当前正在执行的 Agent 名称（用于 LLM 调用时自动关联）
current_agent: ContextVar[str] = ContextVar("current_agent", default="unknown")


class TraceTracker:
    def __init__(self):
        self._agents: dict[str, dict] = {}
        self._start_times: dict[str, float] = {}

    def start_agent(self, agent_name: str):
        """记录 Agent 开始执行。"""
        self._start_times[agent_name] = time.time()
        if agent_name not in self._agents:
            self._agents[agent_name] = {
                "llm_calls": 0,
                "duration_s": 0,
            }
        current_agent.set(agent_name)

    def end_agent(self, agent_name: str):
        """记录 Agent 执行结束。"""
        if agent_name in self._start_times:
            duration = time.time() - self._start_times[agent_name]
            self._agents[agent_name]["duration_s"] = round(duration, 2)
            del self._start_times[agent_name]

    def log_llm_call(self, agent_name: str = None):
        """记录一次 LLM 调用。不传 agent_name 时自动从 context 获取。"""
        name = agent_name or current_agent.get()
        if name not in self._agents:
            self._agents[name] = {"llm_calls": 0, "duration_s": 0}
        self._agents[name]["llm_calls"] += 1

    def get_summary(self) -> dict:
        """返回所有 Agent 的执行轨迹汇总。"""
        total_duration = sum(a["duration_s"] for a in self._agents.values())
        total_llm_calls = sum(a["llm_calls"] for a in self._agents.values())

        agents_detail = []
        for name, data in self._agents.items():
            agents_detail.append({
                "agent": name,
                "duration_s": data["duration_s"],
                "llm_calls": data["llm_calls"],
                "pct_of_total": round(data["duration_s"] / total_duration * 100, 1) if total_duration else 0,
            })

        return {
            "total_duration_s": round(total_duration, 2),
            "total_llm_calls": total_llm_calls,
            "agents": agents_detail,
        }

    def reset(self):
        self._agents.clear()
        self._start_times.clear()


trace_tracker = TraceTracker()
