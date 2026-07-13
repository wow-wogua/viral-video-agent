from contextvars import ContextVar


_cost_state_var: ContextVar[dict | None] = ContextVar("cost_state", default=None)
_cost_context_var: ContextVar[tuple[str, str]] = ContextVar(
    "cost_context", default=("unknown", "unknown")
)


class CostTracker:
    # 定价单位：美元/百万 token
    # MiMo 未在项目内配置估价，0 只表示“本地估价未知”，不代表供应商免费。
    # DeepSeek V4 使用 2026-07-13 官方美元价；当前未拆分缓存命中 token，
    # 因此输入统一按 cache miss 价格做保守估算。
    PRICING = {
        "mimo-v2.5-pro":      {"input": 0.0,   "output": 0.0},
        "deepseek-v4-flash":  {"input": 0.14,  "output": 0.28},
        "deepseek-v4-pro":    {"input": 0.435, "output": 0.87},
    }

    @staticmethod
    def _state() -> dict:
        state = _cost_state_var.get()
        if state is None:
            state = {"input_tokens": 0, "output_tokens": 0, "total_cost": 0.0}
            _cost_state_var.set(state)
        return state

    def set_context(self, agent_name: str, model: str):
        _cost_context_var.set((agent_name, model))

    def log_usage(self, agent_name: str, model: str, input_tokens: int, output_tokens: int):
        pricing = self.PRICING.get(model, {"input": 0.0, "output": 0.0})
        cost = (
            input_tokens * pricing["input"] / 1_000_000 +
            output_tokens * pricing["output"] / 1_000_000
        )
        state = self._state()
        state["input_tokens"] += input_tokens
        state["output_tokens"] += output_tokens
        state["total_cost"] += cost
        print(f"[cost] {agent_name}: {input_tokens}+{output_tokens} tokens, ${cost:.4f}")

    def log_response(self, response):
        """从 LangChain 响应记录一次 token 用量，避免回调和手工统计重复计数。"""
        usage = getattr(response, "usage_metadata", None) or {}
        if not usage:
            return
        agent_name, model = _cost_context_var.get()
        self.log_usage(
            agent_name,
            model,
            int(usage.get("input_tokens", 0) or 0),
            int(usage.get("output_tokens", 0) or 0),
        )

    def get_summary(self) -> dict:
        state = self._state()
        return {
            "input_tokens": state["input_tokens"],
            "output_tokens": state["output_tokens"],
            "total_cost": round(state["total_cost"], 6),
        }

    def reset(self):
        _cost_state_var.set({"input_tokens": 0, "output_tokens": 0, "total_cost": 0.0})
        _cost_context_var.set(("unknown", "unknown"))


cost_tracker = CostTracker()
