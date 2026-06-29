class CostTracker:
    # 定价单位：美元/百万 token
    # MiMo：免费
    # DeepSeek：官方价 ¥1/¥2 (chat), ¥4/¥16 (reasoner) per 百万 token，按 ¥7.2/$1 换算
    PRICING = {
        "mimo-v2.5-pro":      {"input": 0.0,   "output": 0.0},
        "deepseek-chat":      {"input": 0.139,  "output": 0.278},
        "deepseek-reasoner":  {"input": 0.556,  "output": 2.222},
    }

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0

    def log_usage(self, agent_name: str, model: str, input_tokens: int, output_tokens: int):
        pricing = self.PRICING.get(model, {"input": 0.0, "output": 0.0})
        cost = (
            input_tokens * pricing["input"] / 1_000_000 +
            output_tokens * pricing["output"] / 1_000_000
        )
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += cost
        print(f"[cost] {agent_name}: {input_tokens}+{output_tokens} tokens, ${cost:.4f}")

    def get_summary(self) -> dict:
        return {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_cost": round(self.total_cost, 6),
        }

    def reset(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0


cost_tracker = CostTracker()
