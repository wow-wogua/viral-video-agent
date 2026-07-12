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
from src.api.status import result_status

router = APIRouter()
graph = build_graph()

# Redis 异步客户端（用于历史记录和状态查询）
try:
    import redis.asyncio as redis_lib
    from src.config import REDIS_URL
    redis_client = redis_lib.from_url(REDIS_URL, decode_responses=True)
    USE_REDIS = True
except Exception:
    USE_REDIS = False
    redis_client = None


async def _save_to_redis(session_id: str, data: dict):
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
            "termination_reason": data.get("termination_reason", ""),
            "error": data.get("error", ""),
            "report": data.get("report", ""),
            "plan": json.dumps(data.get("plan", []), ensure_ascii=False),
            "cost": json.dumps(data.get("cost", {}), ensure_ascii=False),
            "trace": json.dumps(data.get("trace", {}), ensure_ascii=False),
            "fallback": json.dumps(data.get("fallback", {}), ensure_ascii=False),
            "prompt_version": data.get("prompt_version", "v1"),
        }
        await redis_client.hset(f"history:{session_id}", mapping=record)
        await redis_client.expire(f"history:{session_id}", 86400 * 7)  # 7天过期
        # 加到历史列表
        await redis_client.lrem("history:list", 0, session_id)
        await redis_client.lpush("history:list", session_id)
        await redis_client.ltrim("history:list", 0, 99)  # 最多保留100条
        user_id = record["user_id"]
        if user_id:
            user_history_key = f"history:list:{user_id}"
            await redis_client.lrem(user_history_key, 0, session_id)
            await redis_client.lpush(user_history_key, session_id)
            await redis_client.ltrim(user_history_key, 0, 99)
            await redis_client.expire(user_history_key, 86400 * 7)
    except Exception as e:
        print(f"[redis] 保存历史失败: {e}")


def _result_status(result: dict) -> tuple[str, str]:
    """把图终止原因转换为API状态，避免空报告仍标记completed。"""
    return result_status(result)


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    session_id = request.session_id or str(uuid.uuid4())
    user_id = request.user_id or session_id
    config = {"configurable": {"thread_id": session_id}}
    cost_tracker.reset()
    fallback_counter.reset()
    trace_tracker.reset()
    await _save_to_redis(session_id, {
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
        await _save_to_redis(session_id, {
            "query": request.query,
            "platform": request.platforms[0] if request.platforms else "bilibili",
            "user_id": user_id,
            "status": "failed",
            "termination_reason": "analysis_exception",
            "error": str(exc),
        })
        raise HTTPException(status_code=500, detail="analysis failed") from exc
    cost = cost_tracker.get_summary()
    report = result.get("report_final", "")
    plan = result.get("plan", [])
    status, termination_reason = _result_status(result)
    fallback_summary = fallback_counter.get_summary()
    trace_summary = trace_tracker.get_summary()
    # 保存到 Redis
    await _save_to_redis(session_id, {
        "query": request.query,
        "platform": request.platforms[0] if request.platforms else "bilibili",
        "user_id": user_id,
        "status": status,
        "termination_reason": termination_reason,
        "report": report,
        "plan": plan,
        "cost": cost,
        "fallback": fallback_summary,
        "trace": trace_summary,
        "prompt_version": prompt_manager.current_version,
    })
    return AnalyzeResponse(
        session_id=session_id,
        status=status,
        termination_reason=termination_reason,
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
        await _save_to_redis(session_id, {
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
            await _save_to_redis(session_id, {
                "query": request.query,
                "platform": request.platforms[0] if request.platforms else "bilibili",
                "user_id": user_id,
                "status": "failed",
                "termination_reason": "analysis_exception",
                "error": str(exc),
            })
            yield f"data: {json.dumps({'agent': 'error', 'message': 'analysis failed'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'agent': 'done', 'status': 'failed', 'termination_reason': 'analysis_exception', 'session_id': session_id})}\n\n"
            return

        try:
            # 流结束后通过 aget_state 取最终状态
            state = await graph.aget_state(config)
            values = state.values if state else {}
            report = values.get("report_final", "")
            plan = values.get("plan", [])
            cost = cost_tracker.get_summary()
            status, termination_reason = _result_status(values)

            # 保存到 Redis
            fallback_summary = fallback_counter.get_summary()
            trace_summary = trace_tracker.get_summary()
            await _save_to_redis(session_id, {
                "query": request.query,
                "platform": request.platforms[0] if request.platforms else "bilibili",
                "user_id": user_id,
                "status": status,
                "termination_reason": termination_reason,
                "report": report,
                "plan": plan,
                "cost": cost,
                "fallback": fallback_summary,
                "trace": trace_summary,
                "prompt_version": prompt_manager.current_version,
            })

            yield f"data: {json.dumps({'agent': 'report', 'status': status, 'termination_reason': termination_reason, 'report': report, 'plan': plan}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'agent': 'cost', **cost, 'fallback': fallback_summary, 'trace': trace_summary, 'prompt_version': prompt_manager.current_version}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'agent': 'done', 'status': status, 'termination_reason': termination_reason, 'session_id': session_id})}\n\n"
        except Exception as exc:
            await _save_to_redis(session_id, {
                "query": request.query,
                "platform": request.platforms[0] if request.platforms else "bilibili",
                "user_id": user_id,
                "status": "failed",
                "termination_reason": "state_unavailable",
                "error": str(exc),
            })
            yield f"data: {json.dumps({'agent': 'error', 'message': 'analysis state unavailable'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'agent': 'done', 'status': 'failed', 'termination_reason': 'state_unavailable', 'session_id': session_id})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/sessions/{session_id}/status")
async def get_status(session_id: str, user_id: str | None = None):
    """查询任务状态（从 Redis 读取）。"""
    if USE_REDIS:
        try:
            record = await redis_client.hgetall(f"history:{session_id}")
            if record:
                if user_id and record.get("user_id") != user_id:
                    return {"session_id": session_id, "status": "not_found"}
                return {
                    "session_id": session_id,
                    "status": record.get("status", "completed"),
                    "termination_reason": record.get("termination_reason", ""),
                    "report": record.get("report", ""),
                    "plan": json.loads(record.get("plan", "[]")),
                    "cost": json.loads(record.get("cost", "{}")),
                    "error": record.get("error", ""),
                }
        except Exception:
            pass
    return {"session_id": session_id, "status": "not_found"}


@router.get("/history")
async def get_history(user_id: str | None = None):
    """获取历史分析记录列表。"""
    if not USE_REDIS:
        return {"records": [], "source": "mock"}
    try:
        history_key = f"history:list:{user_id}" if user_id else "history:list"
        session_ids = await redis_client.lrange(history_key, 0, 49)
        records = []
        for sid in session_ids:
            record = await redis_client.hgetall(f"history:{sid}")
            if record:
                records.append({
                    "id": record.get("id", sid),
                    "title": record.get("title", ""),
                    "platform": record.get("platform", "bilibili"),
                    "date": record.get("date", ""),
                    "status": record.get("status", "completed"),
                    "termination_reason": record.get("termination_reason", ""),
                })
        return {"records": records, "source": "redis"}
    except Exception as e:
        return {"records": [], "source": f"error: {e}"}


@router.get("/history/{session_id}")
async def get_history_detail(session_id: str, user_id: str | None = None):
    """获取单条历史记录详情。"""
    if USE_REDIS:
        try:
            record = await redis_client.hgetall(f"history:{session_id}")
            if record:
                if user_id and record.get("user_id") != user_id:
                    return {"error": "not found"}
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
