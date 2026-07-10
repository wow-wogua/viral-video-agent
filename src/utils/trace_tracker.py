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
_agents_var: ContextVar[dict[str, dict] | None] = ContextVar("trace_agents", default=None)
_start_times_var: ContextVar[dict[str, float] | None] = ContextVar("trace_start_times", default=None)


class TraceTracker:
    @staticmethod
    def _agents() -> dict[str, dict]:
        agents = _agents_var.get()
        if agents is None:
            agents = {}
            _agents_var.set(agents)
        return agents

    @staticmethod
    def _start_times() -> dict[str, float]:
        start_times = _start_times_var.get()
        if start_times is None:
            start_times = {}
            _start_times_var.set(start_times)
        return start_times

    def start_agent(self, agent_name: str):
        """记录 Agent 开始执行。"""
        start_times = self._start_times()
        agents = self._agents()
        start_times[agent_name] = time.time()
        if agent_name not in agents:
            agents[agent_name] = {
                "llm_calls": 0,
                "duration_s": 0,
            }
        current_agent.set(agent_name)

    def end_agent(self, agent_name: str):
        """记录 Agent 执行结束。"""
        start_times = self._start_times()
        agents = self._agents()
        if agent_name in start_times:
            duration = time.time() - start_times[agent_name]
            agents[agent_name]["duration_s"] = round(duration, 2)
            del start_times[agent_name]

    def log_llm_call(self, agent_name: str = None):
        """记录一次 LLM 调用。不传 agent_name 时自动从 context 获取。"""
        name = agent_name or current_agent.get()
        agents = self._agents()
        if name not in agents:
            agents[name] = {"llm_calls": 0, "duration_s": 0}
        agents[name]["llm_calls"] += 1

    def get_summary(self) -> dict:
        """返回所有 Agent 的执行轨迹汇总。"""
        agents = self._agents()
        total_duration = sum(a["duration_s"] for a in agents.values())
        total_llm_calls = sum(a["llm_calls"] for a in agents.values())

        agents_detail = []
        for name, data in agents.items():
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
        _agents_var.set({})
        _start_times_var.set({})
        current_agent.set("unknown")


trace_tracker = TraceTracker()
