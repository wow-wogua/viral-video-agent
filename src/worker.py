import asyncio
import uuid
from datetime import datetime, timezone

from arq import Retry
from arq.connections import RedisSettings
from sqlalchemy import select

from src.api.errors import ERROR_MESSAGES
from src.config import ASR_MAX_VIDEOS, ASR_MAX_VIDEO_SECONDS, DEFAULT_LLM_MODEL_ID, DEFAULT_LLM_PROVIDER, JOB_MAX_RETRIES, JOB_TIMEOUT_SECONDS, REDIS_URL, WORKER_MAX_JOBS
from src.db.models import CrawlRun as CrawlRunRecord, EvidenceItem, Report, UsageRecord
from src.db.session import async_session_factory
from src.gateway.cost_tracker import cost_tracker
from src.agents.analyst import analyst_node
from src.agents.writer import writer_node
from src.graph.builder import build_graph
from src.graph.v2 import stable_evidence_id
from src.intelligence.contracts import CrawlStatus, SearchRequest
from src.intelligence.providers import BilibiliDevelopmentSearchProvider, ImportSearchProvider
from src.intelligence.search_service import execute_search_snapshot
from src.intelligence.snapshots import persist_search_snapshot
from src.reporting.validation import finalize_report, validate_claims, validate_report_references
from src.repositories import JobRepository
from src.utils.fallback_counter import fallback_counter
from src.utils.trace_tracker import trace_tracker
from src.tools.transcript import TranscriptError, get_transcript

graph = build_graph()


def _select_transcript_candidates(raw_data: list[dict], limit: int, max_seconds: int = ASR_MAX_VIDEO_SECONDS) -> list[str]:
    candidates: list[str] = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("source_url")
        duration = item.get("duration")
        if duration and float(duration) > max_seconds:
            continue
        if url and "bilibili.com" in url and url not in candidates:
            candidates.append(url)
    return candidates[:limit]


async def _event(job_id: uuid.UUID, event_type: str, message: str, progress: int, level: str = "info", redis=None) -> None:
    async with async_session_factory() as db:
        job = await JobRepository(db).get(job_id)
        if job:
            job.progress = progress
            await JobRepository(db).save(job)
            await JobRepository(db).add_event(job_id, event_type, message, progress, level)
    if redis:
        await redis.hset(f"job:{job_id}:status", mapping={"status": event_type, "message": message, "progress": progress})
        await redis.expire(f"job:{job_id}:status", 86400)
        await redis.xadd(f"job:{job_id}:events", {"event_type": event_type, "message": message, "progress": progress, "level": level}, maxlen=200)
        await redis.expire(f"job:{job_id}:events", 86400)


async def _invoke_graph(job_id: uuid.UUID, user_id: uuid.UUID, query: str, platforms: list[str]) -> dict:
    task = asyncio.create_task(graph.ainvoke({"user_id": str(user_id), "user_request": query, "platforms": platforms, "task_complete": False, "data_sufficient": False, "analysis_confidence": 0.0, "report_final": ""}, config={"configurable": {"thread_id": str(job_id)}}))
    while not task.done():
        await asyncio.sleep(1.5)
        async with async_session_factory() as db:
            current = await JobRepository(db).get(job_id)
            if not current or current.status == "cancelled":
                task.cancel()
                raise asyncio.CancelledError
    return await task


async def _job_cancelled(job_id: uuid.UUID) -> bool:
    async with async_session_factory() as db:
        job = await JobRepository(db).get(job_id)
        return not job or job.status == "cancelled"


def _search_provider_for_job(job):
    config = (job.request_filters or {}).get("provider", {})
    kind = config.get("kind", "development")
    if kind == "development":
        return BilibiliDevelopmentSearchProvider()
    if kind == "import":
        if config.get("format") == "json":
            return ImportSearchProvider.from_json(config.get("data"))
        if config.get("format") == "csv":
            return ImportSearchProvider.from_csv(config.get("data") or "")
        raise ValueError("import provider format is missing")
    raise ValueError(f"unsupported search provider: {kind}")


async def _run_content_intelligence_job(job_id: uuid.UUID, redis=None) -> None:
    async with async_session_factory() as db:
        job = await JobRepository(db).get(job_id)
        if not job or job.status == "cancelled":
            return
        provider = _search_provider_for_job(job)
        request = SearchRequest(
            keyword=job.keyword or job.query,
            sort_mode=job.sort_mode,
            time_range=job.time_range,
            partition=job.partition,
            max_pages=job.max_pages,
            analysis_mode=job.analysis_mode,
            filters=(job.request_filters or {}).get("filters", {}),
            idempotency_key=job.idempotency_key,
        )
        existing_run = await db.scalar(select(CrawlRunRecord).where(CrawlRunRecord.job_id == job_id))
        crawl_run_id = str(existing_run.id) if existing_run else None

    await _event(job_id, "collecting", f"正在建立最多 {request.max_pages} 页的B站当前搜索快照。", 15, redis=redis)
    try:
        bundle = await execute_search_snapshot(
            provider,
            request,
            crawl_run_id=crawl_run_id,
            cancel_check=lambda: _job_cancelled(job_id),
        )
    finally:
        await provider.close()

    await _event(job_id, "persisting", "正在保存逐页状态、去重视频和候选账号。", 85, redis=redis)
    async with async_session_factory() as db:
        repo = JobRepository(db)
        job = await repo.get(job_id)
        if not job:
            return
        await persist_search_snapshot(db, job_id, bundle)
        completed_at = datetime.now(timezone.utc)
        provider_kind = bundle.crawl_run.provider.provider_kind
        if job.status == "cancelled" or bundle.crawl_run.status == CrawlStatus.CANCELLED:
            job.status = "cancelled"
            job.error_code = "JOB_CANCELLED"
            job.error_message = ERROR_MESSAGES["JOB_CANCELLED"]
        elif bundle.crawl_run.status == CrawlStatus.SUCCESS:
            job.status = "completed"
            job.error_code = None
            job.error_message = None
        elif bundle.crawl_run.status == CrawlStatus.PARTIAL:
            job.status = "partial"
            job.error_code = "SEARCH_PARTIAL"
            job.error_message = ERROR_MESSAGES["SEARCH_PARTIAL"]
        elif bundle.crawl_run.status == CrawlStatus.EMPTY:
            job.status = "partial"
            job.error_code = "NO_VIDEO_RESULTS"
            job.error_message = ERROR_MESSAGES["NO_VIDEO_RESULTS"]
        else:
            job.status = "failed"
            job.error_code = "BILIBILI_UNAVAILABLE" if provider_kind == "development" else "WORKER_FAILED"
            job.error_message = ERROR_MESSAGES[job.error_code]
        job.progress = 100
        job.completed_at = completed_at
        if provider_kind == "import" and job.status == "completed":
            request_filters = dict(job.request_filters or {})
            provider_config = dict(request_filters.get("provider", {}))
            import_data = provider_config.pop("data", None)
            if import_data is not None:
                import hashlib
                import json
                serialized = json.dumps(import_data, ensure_ascii=False, sort_keys=True, default=str)
                provider_config["payload_sha256"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            request_filters["provider"] = provider_config
            job.request_filters = request_filters
        await db.commit()

    final_event = {
        CrawlStatus.SUCCESS: ("completed", "搜索快照已完成；P0-B未生成竞品排名或情报报告。", "info"),
        CrawlStatus.PARTIAL: ("partial", "搜索快照部分成功，请查看逐页错误和覆盖说明。", "warning"),
        CrawlStatus.EMPTY: ("partial", "所有请求页均成功但没有规范化视频。", "warning"),
        CrawlStatus.FAILED: ("failed", "没有成功响应页，已保存失败状态。", "error"),
        CrawlStatus.CANCELLED: ("cancelled", "搜索快照已取消。", "warning"),
    }[bundle.crawl_run.status]
    await _event(job_id, final_event[0], final_event[1], 100, final_event[2], redis)


async def _enrich_deep_analysis(result: dict, job_id: uuid.UUID, redis=None) -> dict:
    candidates = _select_transcript_candidates(result.get("raw_data", []), ASR_MAX_VIDEOS, ASR_MAX_VIDEO_SECONDS)
    transcript_data, transcript_evidence, total_seconds = [], [], 0.0
    for index, url in enumerate(candidates, 1):
        await _event(job_id, "transcribing", f"正在转写本次样本中的公开视频 {index}/{len(candidates)}。", 45 + index * 4, redis=redis)
        try:
            transcript = await get_transcript(url)
        except TranscriptError:
            continue
        if not transcript or not transcript.get("text"): continue
        evidence_id = stable_evidence_id("get_transcript", {"url": url})
        total_seconds += float(transcript.get("asr_seconds", 0))
        transcript_data.append({"title": f"视频转写 {index}", "source_url": url, "text": transcript["text"], "segments": transcript.get("segments", []), "_evidence_id": evidence_id})
        transcript_evidence.append({"evidence_id": evidence_id, "tool": "get_transcript", "source_type": "transcript", "title": f"视频转写 {index}", "source_url": url, "platform": "bilibili", "fetched_at": transcript["fetched_at"], "raw_data": {"provider": transcript["provider"], "model": transcript["model"], "audio_hash": transcript["audio_hash"]}, "summary": transcript["text"][:300], "data_fields": {}, "transcript_segment": {"text": transcript["text"], "segments": transcript.get("segments", [])}})
    if not transcript_data:
        await _event(job_id, "analyzing", "ASR不可用或转写失败，已降级为元数据分析。", 68, "warning", redis)
        result["asr_seconds"] = 0
        return result
    state = {**result, "raw_data": result.get("raw_data", []) + transcript_data, "evidence": result.get("evidence", []) + transcript_evidence, "analysis": {}, "analysis_iterations": 0, "analysis_confidence": 0.0, "report_draft": "", "report_final": "", "report_revision_count": 0}
    await _event(job_id, "analyzing", "正在分析口播、脚本结构与开头钩子。", 70, redis=redis)
    state.update(await analyst_node(state))
    state.update(await writer_node(state))
    state.update(await writer_node(state))
    state["asr_seconds"] = total_seconds
    return state


def _error_code(exc: Exception) -> tuple[str, bool]:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "429" in message or "rate" in name: return "LLM_RATE_LIMITED", True
    if "401" in message or "403" in message or "authentication" in name: return "LLM_AUTH_FAILED", False
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or "timeout" in name: return "LLM_TIMEOUT", True
    if "bilibili" in message: return "BILIBILI_UNAVAILABLE", True
    return "WORKER_FAILED", True


async def _persist_result(job_id: uuid.UUID, result: dict) -> uuid.UUID:
    evidence = result.get("evidence", [])
    claims = result.get("analysis", {}).get("claims", [])
    valid, reason = validate_claims(claims, evidence)
    if not valid:
        raise ValueError(f"REPORT_VALIDATION_FAILED: {reason}")
    content = finalize_report(result.get("report_final", ""), claims, evidence)
    valid, reason = validate_report_references(content, evidence)
    if not valid:
        raise ValueError(f"REPORT_VALIDATION_FAILED: {reason}")
    cost = cost_tracker.get_summary()
    trace = trace_tracker.get_summary()
    status = "completed" if result.get("report_final") and not result.get("termination_reason") else "partial"
    async with async_session_factory() as db:
        repo = JobRepository(db)
        job = await repo.get(job_id)
        if not job or job.status == "cancelled":
            raise asyncio.CancelledError
        report = Report(job_id=job.id, user_id=job.user_id, title=job.query[:300], content=content, structured_claims=claims, status=status, model_info={"provider": DEFAULT_LLM_PROVIDER, "model": DEFAULT_LLM_MODEL_ID, "workflow": result.get("workflow_version", "v2"), "trace": trace, "fallback": fallback_counter.get_summary()})
        db.add(report)
        await db.flush()
        for item in evidence:
            db.add(EvidenceItem(report_id=report.id, job_id=job.id, evidence_id=item["evidence_id"], tool=item.get("tool", "unknown"), source_type=item.get("source_type", "tool_result"), title=item.get("title", "Evidence"), source_url=item.get("source_url"), platform=item.get("platform", "bilibili"), fetched_at=datetime.fromisoformat(item["fetched_at"]), raw_data=item.get("raw_data", {}), summary=item.get("summary"), data_fields=item.get("data_fields", {}), transcript_segment=item.get("transcript_segment")))
        db.add(UsageRecord(user_id=job.user_id, job_id=job.id, input_tokens=cost["input_tokens"], output_tokens=cost["output_tokens"], estimated_cost=cost["total_cost"], asr_seconds=float(result.get("asr_seconds", 0))))
        job.status, job.progress, job.completed_at = status, 100, datetime.now(timezone.utc)
        if status == "partial":
            job.error_code, job.error_message = "EVIDENCE_INSUFFICIENT", ERROR_MESSAGES["EVIDENCE_INSUFFICIENT"]
        await db.commit()
        return report.id


async def run_analysis_job(ctx: dict, job_id_value: str) -> None:
    job_id = uuid.UUID(job_id_value)
    redis = ctx.get("redis")
    async with async_session_factory() as db:
        repo = JobRepository(db); job = await repo.get(job_id)
        if not job or job.status == "cancelled": return
        job.status, job.started_at, job.error_code, job.error_message = "running", datetime.now(timezone.utc), None, None
        await repo.save(job)
        user_id, query, platforms, retry_count, analysis_mode, task_mode = job.user_id, job.query, job.platforms, job.retry_count, job.analysis_mode, job.task_mode
    cost_tracker.reset(); fallback_counter.reset(); trace_tracker.reset()
    try:
        if task_mode == "content_intelligence":
            async with ctx["provider_semaphore"]:
                await asyncio.wait_for(_run_content_intelligence_job(job_id, redis), timeout=JOB_TIMEOUT_SECONDS)
            return
        await _event(job_id, "collecting", "正在采集B站数据并检索知识库。", 15, redis=redis)
        async with ctx["provider_semaphore"]:
            result = await asyncio.wait_for(_invoke_graph(job_id, user_id, query, platforms), timeout=JOB_TIMEOUT_SECONDS)
            if analysis_mode == "deep":
                result = await _enrich_deep_analysis(result, job_id, redis)
        await _event(job_id, "validating", "正在校验 Evidence 与结构化结论。", 78, redis=redis)
        await _event(job_id, "persisting", "正在保存报告、证据和用量记录。", 92, redis=redis)
        await _persist_result(job_id, result)
        final_status = "partial" if result.get("termination_reason") else "completed"
        await _event(job_id, final_status, "报告已生成。" if final_status == "completed" else "已保存可用的部分结果。", 100, redis=redis)
    except asyncio.CancelledError:
        return
    except Exception as exc:
        code, retryable = _error_code(exc)
        if "REPORT_VALIDATION_FAILED" in str(exc): code, retryable = "REPORT_VALIDATION_FAILED", False
        if code == "REPORT_VALIDATION_FAILED":
            print(f"[worker] {code}: {str(exc)[:240]}")
        else:
            print(f"[worker] {code}: {type(exc).__name__}")
        async with async_session_factory() as db:
            repo = JobRepository(db); job = await repo.get(job_id)
            if not job or job.status == "cancelled": return
            if retryable and retry_count < JOB_MAX_RETRIES:
                job.retry_count += 1; job.status = "pending"; await repo.save(job)
                await repo.add_event(job_id, "queued", f"临时故障，{2 ** job.retry_count * 5} 秒后自动重试。", job.progress, "warning")
                raise Retry(defer=2 ** job.retry_count * 5) from exc
            job.status, job.error_code, job.error_message = "failed", code, ERROR_MESSAGES.get(code, ERROR_MESSAGES["WORKER_FAILED"])
            await repo.save(job); await repo.add_event(job_id, "failed", job.error_message, job.progress, "error")


async def startup(ctx: dict) -> None:
    ctx["provider_semaphore"] = asyncio.Semaphore(WORKER_MAX_JOBS)


class WorkerSettings:
    functions = [run_analysis_job]
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    max_jobs = WORKER_MAX_JOBS
    job_timeout = JOB_TIMEOUT_SECONDS + 30
    on_startup = startup
