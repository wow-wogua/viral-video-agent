import uuid
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from src.api.schemas import AnalyzeRequest, AnalyzeResponse
from src.graph.builder import build_graph
from src.gateway.cost_tracker import cost_tracker
from src.utils.fallback_counter import fallback_counter
from src.utils.trace_tracker import trace_tracker
from src.prompts.manager import prompt_manager

router = APIRouter()
graph = build_graph()

# Redis 客户端（用于历史记录持久化）
try:
    import redis as redis_lib
    from src.config import REDIS_URL
    redis_client = redis_lib.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    USE_REDIS = True
except Exception:
    USE_REDIS = False
    redis_client = None


def _save_to_redis(session_id: str, data: dict):
    """保存分析结果到 Redis，用于历史记录和状态查询。"""
    if not USE_REDIS:
        return
    try:
        record = {
            "id": session_id,
            "title": data.get("query", "")[:30],
            "platform": data.get("platform", "bilibili"),
            "user_id": data.get("user_id", ""),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "status": data.get("status", "completed"),
            "error": data.get("error", ""),
            "report": data.get("report", ""),
            "plan": json.dumps(data.get("plan", []), ensure_ascii=False),
            "cost": json.dumps(data.get("cost", {}), ensure_ascii=False),
            "trace": json.dumps(data.get("trace", {}), ensure_ascii=False),
            "fallback": json.dumps(data.get("fallback", {}), ensure_ascii=False),
            "prompt_version": data.get("prompt_version", "v1"),
        }
        redis_client.hset(f"history:{session_id}", mapping=record)
        redis_client.expire(f"history:{session_id}", 86400 * 7)  # 7天过期
        # 加到历史列表
        redis_client.lrem("history:list", 0, session_id)
        redis_client.lpush("history:list", session_id)
        redis_client.ltrim("history:list", 0, 99)  # 最多保留100条
    except Exception as e:
        print(f"[redis] 保存历史失败: {e}")


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    session_id = request.session_id or str(uuid.uuid4())
    user_id = request.user_id or session_id
    config = {"configurable": {"thread_id": session_id}}
    cost_tracker.reset()
    fallback_counter.reset()
    trace_tracker.reset()
    _save_to_redis(session_id, {
        "query": request.query,
        "platform": request.platforms[0] if request.platforms else "bilibili",
        "user_id": user_id,
        "status": "running",
    })
    try:
        result = await graph.ainvoke({
            "user_id": user_id,
            "user_request": request.query,
            "platforms": request.platforms,
            "task_complete": False,
            "data_sufficient": False,
            "analysis_confidence": 0.0,
            "report_final": "",
        }, config=config)
    except Exception as exc:
        _save_to_redis(session_id, {
            "query": request.query,
            "platform": request.platforms[0] if request.platforms else "bilibili",
            "user_id": user_id,
            "status": "failed",
            "error": str(exc),
        })
        raise HTTPException(status_code=500, detail="analysis failed") from exc
    cost = cost_tracker.get_summary()
    report = result.get("report_final", "")
    plan = result.get("plan", [])
    fallback_summary = fallback_counter.get_summary()
    trace_summary = trace_tracker.get_summary()
    # 保存到 Redis
    _save_to_redis(session_id, {
        "query": request.query,
        "platform": request.platforms[0] if request.platforms else "bilibili",
        "user_id": user_id,
        "status": "completed",
        "report": report,
        "plan": plan,
        "cost": cost,
        "fallback": fallback_summary,
        "trace": trace_summary,
        "prompt_version": prompt_manager.current_version,
    })
    return AnalyzeResponse(
        session_id=session_id,
        status="completed",
        report=report,
        plan=plan,
        cost=cost,
    )


@router.post("/analyze/stream")
async def analyze_stream(request: AnalyzeRequest):
    """SSE 流式输出：实时推送 Agent 工作进度。"""
    session_id = request.session_id or str(uuid.uuid4())
    user_id = request.user_id or session_id
    config = {"configurable": {"thread_id": session_id}}
    cost_tracker.reset()
    fallback_counter.reset()
    trace_tracker.reset()

    async def event_generator():
        cost_tracker.reset()
        fallback_counter.reset()
        trace_tracker.reset()
        _save_to_redis(session_id, {
            "query": request.query,
            "platform": request.platforms[0] if request.platforms else "bilibili",
            "user_id": user_id,
            "status": "running",
        })
        try:
            async for event in graph.astream_events(
                {
                    "user_id": user_id,
                    "user_request": request.query,
                    "platforms": request.platforms,
                    "task_complete": False,
                    "data_sufficient": False,
                    "analysis_confidence": 0.0,
                    "report_final": "",
                },
                config=config,
                version="v2",
            ):
                if event["event"] == "on_chain_end":
                    data = {
                        "agent": event["name"],
                        "output": str(event["data"])[:500],
                    }
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as exc:
            _save_to_redis(session_id, {
                "query": request.query,
                "platform": request.platforms[0] if request.platforms else "bilibili",
                "user_id": user_id,
                "status": "failed",
                "error": str(exc),
            })
            yield f"data: {json.dumps({'agent': 'error', 'message': 'analysis failed'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'agent': 'done', 'session_id': session_id})}\n\n"
            return

        try:
            # 流结束后通过 aget_state 取最终状态
            state = await graph.aget_state(config)
            values = state.values if state else {}
            report = values.get("report_final", "")
            plan = values.get("plan", [])
            cost = cost_tracker.get_summary()

            # 保存到 Redis
            fallback_summary = fallback_counter.get_summary()
            trace_summary = trace_tracker.get_summary()
            _save_to_redis(session_id, {
                "query": request.query,
                "platform": request.platforms[0] if request.platforms else "bilibili",
                "user_id": user_id,
                "status": "completed",
                "report": report,
                "plan": plan,
                "cost": cost,
                "fallback": fallback_summary,
                "trace": trace_summary,
                "prompt_version": prompt_manager.current_version,
            })

            yield f"data: {json.dumps({'agent': 'report', 'report': report, 'plan': plan}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'agent': 'cost', **cost, 'fallback': fallback_summary, 'trace': trace_summary, 'prompt_version': prompt_manager.current_version}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'agent': 'done', 'session_id': session_id})}\n\n"
        except Exception as exc:
            _save_to_redis(session_id, {
                "query": request.query,
                "platform": request.platforms[0] if request.platforms else "bilibili",
                "user_id": user_id,
                "status": "failed",
                "error": str(exc),
            })
            yield f"data: {json.dumps({'agent': 'error', 'message': 'analysis state unavailable'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'agent': 'done', 'session_id': session_id})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/sessions/{session_id}/status")
async def get_status(session_id: str):
    """查询任务状态（从 Redis 读取）。"""
    if USE_REDIS:
        try:
            record = redis_client.hgetall(f"history:{session_id}")
            if record:
                return {
                    "session_id": session_id,
                    "status": record.get("status", "completed"),
                    "report": record.get("report", ""),
                    "plan": json.loads(record.get("plan", "[]")),
                    "cost": json.loads(record.get("cost", "{}")),
                    "error": record.get("error", ""),
                }
        except Exception:
            pass
    return {"session_id": session_id, "status": "not_found"}


@router.get("/history")
async def get_history():
    """获取历史分析记录列表。"""
    if not USE_REDIS:
        return {"records": [], "source": "mock"}
    try:
        session_ids = redis_client.lrange("history:list", 0, 49)
        records = []
        for sid in session_ids:
            record = redis_client.hgetall(f"history:{sid}")
            if record:
                records.append({
                    "id": record.get("id", sid),
                    "title": record.get("title", ""),
                    "platform": record.get("platform", "bilibili"),
                    "date": record.get("date", ""),
                    "status": record.get("status", "completed"),
                })
        return {"records": records, "source": "redis"}
    except Exception as e:
        return {"records": [], "source": f"error: {e}"}


@router.get("/history/{session_id}")
async def get_history_detail(session_id: str):
    """获取单条历史记录详情。"""
    if USE_REDIS:
        try:
            record = redis_client.hgetall(f"history:{session_id}")
            if record:
                return {
                    "id": record.get("id", session_id),
                    "title": record.get("title", ""),
                    "platform": record.get("platform", "bilibili"),
                    "date": record.get("date", ""),
                    "status": record.get("status", "completed"),
                    "report": record.get("report", ""),
                    "plan": json.loads(record.get("plan", "[]")),
                    "cost": json.loads(record.get("cost", "{}")),
                    "trace": json.loads(record.get("trace", "{}")),
                    "fallback": json.loads(record.get("fallback", "{}")),
                    "prompt_version": record.get("prompt_version", "v1"),
                }
        except Exception:
            pass
    return {"error": "not found"}
