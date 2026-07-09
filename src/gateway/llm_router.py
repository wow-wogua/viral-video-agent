from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import BaseCallbackHandler
from src.config import (
    ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, LLM_MODEL_ID,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL_ID,
)
from src.gateway.model_registry import model_registry
from src.gateway.cost_tracker import cost_tracker


class CostCallbackHandler(BaseCallbackHandler):
    """LLM 回调：记录 token 消耗。"""

    def __init__(self, agent_name: str, model: str):
        self.agent_name = agent_name
        self.model = model

    def on_llm_end(self, response, **kwargs):
        usage = response.llm_output.get("usage", {}) if response.llm_output else {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        if input_tokens or output_tokens:
            cost_tracker.log_usage(self.agent_name, self.model, input_tokens, output_tokens)


def _build_anthropic(model: str, base_url: str, api_key: str, enable_thinking: bool = False) -> ChatAnthropic:
    kwargs = {}
    if not enable_thinking:
        kwargs["thinking"] = {"type": "disabled"}
    return ChatAnthropic(
        model=model,
        anthropic_api_url=base_url,
        api_key=api_key,
        model_kwargs=kwargs,
    )


def _build_deepseek(model: str = None, base_url: str = None, api_key: str = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or DEEPSEEK_MODEL_ID,
        base_url=base_url or DEEPSEEK_BASE_URL,
        api_key=api_key or DEEPSEEK_API_KEY,
    )


# Analyst 开启 thinking（需要深度推理），其他 Agent 关闭
_THINKING_AGENTS = {"analyst"}

def get_llm(agent_name: str = "default"):
    """获取 LLM 实例。优先查 ModelRegistry，没有则用默认模型。"""
    enable_thinking = agent_name in _THINKING_AGENTS
    registered = model_registry.get_model(agent_name)
    if registered:
        provider = registered.get("provider", "anthropic")
        model = registered["model"]
        if provider in ("deepseek", "openai"):
            # DeepSeek 和 OpenAI 兼容接口都用 ChatOpenAI
            llm = _build_deepseek(model, registered.get("base_url"), registered.get("api_key"))
        else:
            llm = _build_anthropic(model, registered.get("base_url", ANTHROPIC_BASE_URL),
                                    registered.get("api_key", ANTHROPIC_API_KEY),
                                    enable_thinking=enable_thinking)
    else:
        model = LLM_MODEL_ID
        llm = _build_anthropic(model, ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY,
                                enable_thinking=enable_thinking)

    # 挂载成本追踪回调
    llm.callbacks = [CostCallbackHandler(agent_name, model)]
    return llm
