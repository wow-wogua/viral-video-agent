from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from src.config import (
    ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL_ID, DEFAULT_LLM_PROVIDER,
    MIMO_API_KEY, MIMO_CHAT_MODEL_ID, MIMO_OPENAI_BASE_URL,
)
from src.gateway.model_registry import model_registry
from src.gateway.cost_tracker import cost_tracker


def _build_anthropic(
    model: str,
    base_url: str,
    api_key: str,
    enable_thinking: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
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
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return ChatAnthropic(**kwargs)


def _build_openai_compatible(
    model: str,
    base_url: str,
    api_key: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    disable_thinking: bool = False,
) -> ChatOpenAI:
    kwargs = dict(
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if disable_thinking:
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    return ChatOpenAI(**kwargs)


# Analyst 必须返回可解析的结构化 JSON。真实 MiMo 冒烟中 thinking 模式可能只返回
# thinking block 而没有 text block，因此产品主链路统一要求文本输出。
_THINKING_AGENTS: set[str] = set()
_AGENT_MAX_TOKENS = {"analyst": 2048, "writer": 2048}

def get_llm(agent_name: str = "default", temperature: float | None = None):
    """获取 LLM 实例。优先查 ModelRegistry，没有则用默认模型。"""
    enable_thinking = agent_name in _THINKING_AGENTS
    max_tokens = _AGENT_MAX_TOKENS.get(agent_name)
    registered = model_registry.get_model(agent_name)
    if registered:
        provider = registered.get("provider", "anthropic")
        model = registered["model"]
        if provider in ("deepseek", "openai", "mimo"):
            if provider == "mimo":
                base_url = registered.get("base_url") or MIMO_OPENAI_BASE_URL
                api_key = registered.get("api_key") or MIMO_API_KEY
            elif provider == "deepseek":
                base_url = registered.get("base_url") or DEEPSEEK_BASE_URL
                api_key = registered.get("api_key") or DEEPSEEK_API_KEY
            else:
                base_url = registered.get("base_url", "")
                api_key = registered.get("api_key", "")
            llm = _build_openai_compatible(
                model,
                base_url,
                api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                disable_thinking=provider == "deepseek" and not enable_thinking,
            )
        else:
            llm = _build_anthropic(model, registered.get("base_url", ANTHROPIC_BASE_URL),
                                    registered.get("api_key", ANTHROPIC_API_KEY),
                                    enable_thinking=enable_thinking,
                                    temperature=temperature,
                                    max_tokens=max_tokens)
    else:
        if DEFAULT_LLM_PROVIDER == "deepseek":
            model = DEEPSEEK_MODEL_ID
            llm = _build_openai_compatible(
                model=model,
                base_url=DEEPSEEK_BASE_URL,
                api_key=DEEPSEEK_API_KEY,
                temperature=temperature,
                max_tokens=max_tokens,
                disable_thinking=not enable_thinking,
            )
        else:
            model = MIMO_CHAT_MODEL_ID
            llm = _build_openai_compatible(
                model=model,
                base_url=MIMO_OPENAI_BASE_URL,
                api_key=MIMO_API_KEY,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    cost_tracker.set_context(agent_name, model)
    return llm
