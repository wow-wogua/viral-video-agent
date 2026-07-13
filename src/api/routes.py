from fastapi import APIRouter

from src.api.auth_routes import router as auth_router
from src.api.job_routes import router as job_router
from src.api.report_routes import router as report_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(job_router)
router.include_router(report_router)
