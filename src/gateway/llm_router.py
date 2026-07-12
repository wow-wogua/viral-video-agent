from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from src.config import (
    ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, LLM_MODEL_ID,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL_ID,
)
from src.gateway.model_registry import model_registry
from src.gateway.cost_tracker import cost_tracker


def _build_anthropic(
    model: str,
    base_url: str,
    api_key: str,
    enable_thinking: bool = False,
    temperature: float | None = None,
) -> ChatAnthropic:
    kwargs = dict(
        model=model,
        anthropic_api_url=base_url,
        api_key=api_key,
    )
    if not enable_thinking:
        kwargs["thinking"] = {"type": "disabled"}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return ChatAnthropic(**kwargs)


def _build_deepseek(
    model: str = None,
    base_url: str = None,
    api_key: str = None,
    temperature: float | None = None,
) -> ChatOpenAI:
    kwargs = dict(
        model=model or DEEPSEEK_MODEL_ID,
        base_url=base_url or DEEPSEEK_BASE_URL,
        api_key=api_key or DEEPSEEK_API_KEY,
    )
    if temperature is not None:
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)


# Analyst 开启 thinking（需要深度推理），其他 Agent 关闭
_THINKING_AGENTS = {"analyst"}

def get_llm(agent_name: str = "default", temperature: float | None = None):
    """获取 LLM 实例。优先查 ModelRegistry，没有则用默认模型。"""
    enable_thinking = agent_name in _THINKING_AGENTS
    registered = model_registry.get_model(agent_name)
    if registered:
        provider = registered.get("provider", "anthropic")
        model = registered["model"]
        if provider in ("deepseek", "openai"):
            # DeepSeek 和 OpenAI 兼容接口都用 ChatOpenAI
            llm = _build_deepseek(
                model,
                registered.get("base_url"),
                registered.get("api_key"),
                temperature=temperature,
            )
        else:
            llm = _build_anthropic(model, registered.get("base_url", ANTHROPIC_BASE_URL),
                                    registered.get("api_key", ANTHROPIC_API_KEY),
                                    enable_thinking=enable_thinking,
                                    temperature=temperature)
    else:
        model = LLM_MODEL_ID
        llm = _build_anthropic(model, ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY,
                                enable_thinking=enable_thinking,
                                temperature=temperature)

    cost_tracker.set_context(agent_name, model)
    return llm
