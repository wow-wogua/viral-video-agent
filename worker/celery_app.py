from celery import Celery
from src.config import REDIS_URL

celery_app = Celery("viral-video", broker = REDIS_URL)
celery_app.conf.update(
    task_concurrency=3,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=600,
)