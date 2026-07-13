from src.gateway import llm_router


def test_openai_builder_uses_official_deepseek_thinking_toggle(monkeypatch):
    captured = {}
    sentinel = object()

    def fake_chat_openai(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(llm_router, "ChatOpenAI", fake_chat_openai)

    assert llm_router._build_openai_compatible(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com",
        api_key="test-key",
        disable_thinking=True,
    ) is sentinel
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


def test_analyst_uses_text_output_mode_for_structured_json(monkeypatch):
    captured = {}
    sentinel = object()

    def fake_build(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(llm_router.model_registry, "get_model", lambda _agent: None)
    monkeypatch.setattr(llm_router, "DEFAULT_LLM_PROVIDER", "mimo")
    monkeypatch.setattr(llm_router, "_build_openai_compatible", fake_build)
    monkeypatch.setattr(llm_router.cost_tracker, "set_context", lambda *_args: None)

    assert llm_router.get_llm("analyst") is sentinel
    assert captured["model"] == llm_router.MIMO_CHAT_MODEL_ID
    assert captured["base_url"] == llm_router.MIMO_OPENAI_BASE_URL
    assert captured["api_key"] == llm_router.MIMO_API_KEY
    assert captured["max_tokens"] == 2048


def test_default_provider_can_use_deepseek(monkeypatch):
    captured = {}
    sentinel = object()

    def fake_build(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(llm_router.model_registry, "get_model", lambda _agent: None)
    monkeypatch.setattr(llm_router, "DEFAULT_LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(llm_router, "_build_openai_compatible", fake_build)
    monkeypatch.setattr(llm_router.cost_tracker, "set_context", lambda *_args: None)

    assert llm_router.get_llm("analyst") is sentinel
    assert captured["model"] == "deepseek-v4-pro"
    assert captured["max_tokens"] == 2048
    assert captured["disable_thinking"] is True


def test_registered_mimo_provider_uses_public_openai_compatible_endpoint(monkeypatch):
    captured = {}
    sentinel = object()

    def fake_build(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        llm_router.model_registry,
        "get_model",
        lambda _agent: {"provider": "mimo", "model": "mimo-v2.5-pro"},
    )
    monkeypatch.setattr(llm_router, "_build_openai_compatible", fake_build)
    monkeypatch.setattr(llm_router.cost_tracker, "set_context", lambda *_args: None)

    assert llm_router.get_llm("writer") is sentinel
    assert captured["args"] == (
        "mimo-v2.5-pro",
        llm_router.MIMO_OPENAI_BASE_URL,
        llm_router.MIMO_API_KEY,
    )
    assert captured["max_tokens"] == 2048
