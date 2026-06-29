from fastapi import FastAPI
from src.api.routes import router

app = FastAPI(title="爆款视频分析系统")
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
