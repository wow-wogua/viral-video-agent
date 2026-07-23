from arq import create_pool
from arq.connections import RedisSettings

from src.config import REDIS_URL


class JobQueue:
    def __init__(self, pool=None):
        self.pool = pool

    async def enqueue(self, job_id: str, execution_version: int = 0) -> str:
        pool = self.pool or await create_pool(RedisSettings.from_dsn(REDIS_URL))
        owns_pool = self.pool is None
        arq_job_id = f"analysis:{job_id}:v{execution_version}"
        try:
            await pool.enqueue_job("run_analysis_job", job_id, execution_version, _job_id=arq_job_id)
        finally:
            if owns_pool:
                await pool.aclose()
        return arq_job_id


_job_queue = JobQueue()


def get_job_queue() -> JobQueue:
    return _job_queue
