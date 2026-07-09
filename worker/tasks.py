import json
import redis
from worker.celery_app import celery_app
from src.graph.builder import build_graph
from src.config import REDIS_URL

graph = build_graph()
redis_client = redis.from_url(REDIS_URL)

@celery_app.task(bind=True, max_retries=2)
def run_analysis(self, session_id: str, query: str, platforms: list[str]):
    try:
        result = graph.invoke({
            "user_request": query,
            "platforms": platforms,
            "task_complete": False,
            "data_sufficient": False,
            "analysis_confidence": 0.0,
            "report_final": "",
        }, config={"configurable": {"thread_id": session_id}})
        redis_client.setex(f"result:{session_id}", 3600,
json.dumps(result))
        return result
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30)
