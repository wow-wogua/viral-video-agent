from fastapi import FastAPI
from src.api.errors import AppError, app_error_handler
from src.api.routes import router
from src.gateway.model_bootstrap import configure_optional_model_routes

configure_optional_model_routes()

app = FastAPI(title="爆款视频分析系统")
app.add_exception_handler(AppError, app_error_handler)
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
