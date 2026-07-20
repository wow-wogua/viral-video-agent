import os

from src.gateway.model_registry import model_registry


FINETUNED_RESEARCHER_MODEL = "qwen3-tool-calling"
DEFAULT_FINETUNED_MODEL_URL = "http://localhost:8002/v1"


def configure_optional_model_routes() -> bool:
    """Apply the optional Researcher route from process environment settings."""
    enabled = os.getenv("USE_FINETUNED_MODEL", "false").lower() == "true"
    if not enabled:
        model_registry.unregister("researcher")
        return False

    model_registry.register(
        "researcher",
        {
            "provider": "openai",
            "model": FINETUNED_RESEARCHER_MODEL,
            "base_url": os.getenv("FINETUNED_MODEL_URL") or DEFAULT_FINETUNED_MODEL_URL,
            "api_key": "not-needed",
        },
    )
    return True
