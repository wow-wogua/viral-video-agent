from fastapi import FastAPI
from src.api.routes import router
from src.gateway.model_registry import model_registry

app = FastAPI(title="爆款视频分析系统")
app.include_router(router)

# 注册微调后的工具调用模型（可选，通过环境变量控制是否启用）
import os
if os.getenv("USE_FINETUNED_MODEL", "").lower() == "true":
    model_registry.register(
        "researcher",
        {
            "provider": "openai",  # OpenAI 兼容接口
            "model": "qwen3-tool-calling",
            "base_url": os.getenv("FINETUNED_MODEL_URL", "http://localhost:8002/v1"),
            "api_key": "not-needed",
        },
    )
    print("[main] Researcher 已切换到微调模型", flush=True)


@app.get("/health")
async def health():
    return {"status": "ok"}
