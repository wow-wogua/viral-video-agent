import asyncio
import importlib
import sys

import pytest

from src.gateway import llm_router
from src.gateway.model_bootstrap import configure_optional_model_routes
from src.gateway.model_registry import model_registry


@pytest.fixture(autouse=True)
def restore_model_registry():
    original = {name: config.copy() for name, config in model_registry.MODELS.items()}
    yield
    model_registry.MODELS.clear()
    model_registry.MODELS.update(original)


def _capture_llm_builds(monkeypatch):
    calls = []

    def fake_build(*args, **kwargs):
        calls.append({"args": args, **kwargs})
        return object()

    monkeypatch.setattr(llm_router, "_build_openai_compatible", fake_build)
    monkeypatch.setattr(llm_router.cost_tracker, "set_context", lambda *_args: None)
    monkeypatch.setattr(llm_router, "DEFAULT_LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(llm_router, "DEEPSEEK_MODEL_ID", "deepseek-v4-pro")
    monkeypatch.setattr(llm_router, "DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setattr(llm_router, "DEEPSEEK_API_KEY", "test-only")
    return calls


def test_disabled_route_uses_default_deepseek_for_all_agents(monkeypatch):
    monkeypatch.setenv("USE_FINETUNED_MODEL", "false")
    model_registry.register(
        "researcher",
        {"provider": "openai", "model": "stale", "base_url": "http://stale/v1", "api_key": "not-needed"},
    )

    assert configure_optional_model_routes() is False
    assert model_registry.get_model("researcher") is None

    calls = _capture_llm_builds(monkeypatch)
    for agent_name in ("researcher", "planner", "analyst", "writer"):
        llm_router.get_llm(agent_name)

    assert [call["model"] for call in calls] == ["deepseek-v4-pro"] * 4
    assert all(call["base_url"] == "https://api.deepseek.com" for call in calls)


def test_enabled_route_changes_only_researcher(monkeypatch):
    monkeypatch.setenv("USE_FINETUNED_MODEL", "true")
    monkeypatch.setenv("FINETUNED_MODEL_URL", "http://127.0.0.1:8002/v1")
    preserved = {
        "planner": {"provider": "deepseek", "model": "planner-model"},
        "analyst": {"provider": "deepseek", "model": "analyst-model"},
        "writer": {"provider": "deepseek", "model": "writer-model"},
    }
    for agent_name, config in preserved.items():
        model_registry.register(agent_name, config.copy())

    assert configure_optional_model_routes() is True
    assert model_registry.get_model("researcher") == {
        "provider": "openai",
        "model": "qwen3-tool-calling",
        "base_url": "http://127.0.0.1:8002/v1",
        "api_key": "not-needed",
    }
    for agent_name, config in preserved.items():
        assert model_registry.get_model(agent_name) == config


def test_optional_route_is_idempotent_and_rolls_back_without_global_clear(monkeypatch):
    model_registry.register("analyst", {"provider": "deepseek", "model": "kept"})
    monkeypatch.setenv("USE_FINETUNED_MODEL", "true")
    monkeypatch.setenv("FINETUNED_MODEL_URL", "http://127.0.0.1:8002/v1")

    configure_optional_model_routes()
    first = {name: config.copy() for name, config in model_registry.MODELS.items()}
    configure_optional_model_routes()
    assert model_registry.MODELS == first

    monkeypatch.setenv("USE_FINETUNED_MODEL", "false")
    assert configure_optional_model_routes() is False
    assert model_registry.get_model("researcher") is None
    assert model_registry.get_model("analyst") == {"provider": "deepseek", "model": "kept"}


def test_enabled_researcher_resolves_to_local_service_only(monkeypatch):
    monkeypatch.setenv("USE_FINETUNED_MODEL", "true")
    monkeypatch.setenv("FINETUNED_MODEL_URL", "http://127.0.0.1:8002/v1")
    configure_optional_model_routes()
    calls = _capture_llm_builds(monkeypatch)

    llm_router.get_llm("researcher")
    llm_router.get_llm("planner")
    llm_router.get_llm("analyst")
    llm_router.get_llm("writer")

    assert calls[0]["args"] == (
        "qwen3-tool-calling",
        "http://127.0.0.1:8002/v1",
        "not-needed",
    )
    assert [call["model"] for call in calls[1:]] == ["deepseek-v4-pro"] * 3


def test_worker_startup_uses_shared_bootstrap_and_supports_fallback(monkeypatch):
    import src
    from src.graph import builder

    monkeypatch.setattr(builder, "build_graph", lambda: object())
    previous_worker = sys.modules.pop("src.worker", None)
    try:
        worker = importlib.import_module("src.worker")
        monkeypatch.setenv("USE_FINETUNED_MODEL", "true")
        monkeypatch.setenv("FINETUNED_MODEL_URL", "http://127.0.0.1:8002/v1")
        ctx = {}

        asyncio.run(worker.startup(ctx))

        assert worker.configure_optional_model_routes is configure_optional_model_routes
        assert "provider_semaphore" in ctx
        assert model_registry.get_model("researcher")["base_url"] == "http://127.0.0.1:8002/v1"

        monkeypatch.setenv("USE_FINETUNED_MODEL", "false")
        asyncio.run(worker.startup({}))
        assert model_registry.get_model("researcher") is None
    finally:
        sys.modules.pop("src.worker", None)
        if previous_worker is None:
            if hasattr(src, "worker"):
                delattr(src, "worker")
        else:
            sys.modules["src.worker"] = previous_worker
            src.worker = previous_worker


def test_app_import_uses_the_same_bootstrap(monkeypatch):
    monkeypatch.setenv("USE_FINETUNED_MODEL", "true")
    monkeypatch.setenv("FINETUNED_MODEL_URL", "http://127.0.0.1:8002/v1")
    from src import main

    reloaded = importlib.reload(main)

    assert reloaded.app.title == "爆款视频分析系统"
    assert reloaded.configure_optional_model_routes is configure_optional_model_routes
    assert model_registry.get_model("researcher")["base_url"] == "http://127.0.0.1:8002/v1"

    monkeypatch.setenv("USE_FINETUNED_MODEL", "false")
    importlib.reload(main)
    assert model_registry.get_model("researcher") is None
