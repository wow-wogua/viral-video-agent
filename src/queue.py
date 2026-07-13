from arq import create_pool
from arq.connections import RedisSettings

from src.config import REDIS_URL


class JobQueue:
    async def enqueue(self, job_id: str, retry_count: int = 0) -> str:
        pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
        arq_job_id = f"analysis:{job_id}:{retry_count}"
        try:
            await pool.enqueue_job("run_analysis_job", job_id, _job_id=arq_job_id)
        finally:
            await pool.aclose()
        return arq_job_id


_job_queue = JobQueue()


def get_job_queue() -> JobQueue:
    return _job_queue
