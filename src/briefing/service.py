from dataclasses import dataclass
import uuid

from sqlalchemy import select

from src.briefing.schemas import BriefDecision, TopicSpec
from src.briefing.validator import BriefValidator, conservative_topic_spec
from src.db.models import AnalysisJob, JobClarification, JobEvent
from src.db.session import async_session_factory
from src.gateway.cost_tracker import cost_tracker
from src.repositories import JobRepository


MAX_CLARIFICATION_ROUNDS = 2


@dataclass
class BriefValidationResult:
    ready: bool
    topic_spec: TopicSpec | None = None
    decision: BriefDecision | None = None


def _merge_usage(previous: dict | None, current: dict) -> dict:
    previous = previous or {}
    return {
        "input_tokens": int(previous.get("input_tokens", 0)) + int(current.get("input_tokens", 0)),
        "output_tokens": int(previous.get("output_tokens", 0)) + int(current.get("output_tokens", 0)),
        "estimated_cost": round(float(previous.get("estimated_cost", 0.0)) + float(current.get("total_cost", 0.0)), 6),
        "calls": int(previous.get("calls", 0)) + 1,
    }


async def _history(db, job_id: uuid.UUID) -> list[JobClarification]:
    result = await db.scalars(
        select(JobClarification)
        .where(JobClarification.job_id == job_id)
        .order_by(JobClarification.round.asc())
    )
    return list(result.all())


async def validate_job_brief(
    job_id: uuid.UUID,
    validator: BriefValidator | None = None,
    expected_execution_version: int | None = None,
) -> BriefValidationResult:
    validator = validator or BriefValidator()
    async with async_session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        if not job or job.status != "running":
            return BriefValidationResult(ready=False)
        execution_version = job.execution_version if expected_execution_version is None else expected_execution_version
        if job.execution_version != execution_version:
            return BriefValidationResult(ready=False)
        if job.topic_spec:
            return BriefValidationResult(ready=True, topic_spec=TopicSpec.model_validate(job.topic_spec))

        history_rows = await _history(db, job_id)
        if any(item.status == "pending" for item in history_rows):
            return BriefValidationResult(ready=False)
        next_round = len(history_rows) + 1
        query = job.query
        prompt_history = [
            {
                "round": item.round,
                "question": item.question,
                "selected_option_id": item.selected_option_id,
                "custom_answer": item.custom_answer,
            }
            for item in history_rows
            if item.status == "answered"
        ]

    usage: dict | None = None
    if len(history_rows) >= MAX_CLARIFICATION_ROUNDS:
        topic_spec = conservative_topic_spec(query, prompt_history)
        decision = BriefDecision(
            need_clarification=False,
            verification="达到两轮澄清上限，使用保守假设继续。",
            topic_spec=topic_spec,
            confidence=topic_spec.confidence,
        )
    else:
        decision = await validator.validate(query, prompt_history, next_round)
        usage = cost_tracker.get_summary()

    async with async_session_factory() as db:
        job = await JobRepository(db).get_for_update(job_id)
        if not job:
            return BriefValidationResult(ready=False)
        if usage is not None:
            job.interaction_usage = _merge_usage(job.interaction_usage, usage)
        if job.execution_version != execution_version or job.status != "running":
            await db.commit()
            return BriefValidationResult(ready=False)
        if job.topic_spec:
            await db.commit()
            return BriefValidationResult(ready=True, topic_spec=TopicSpec.model_validate(job.topic_spec))

        if decision.need_clarification and next_round <= MAX_CLARIFICATION_ROUNDS:
            request = JobClarification(
                request_id=uuid.uuid4(),
                job_id=job.id,
                round=next_round,
                question=decision.question or "请补充研究范围。",
                options=[item.model_dump(mode="json") for item in decision.options],
                allow_custom=decision.allow_custom,
                status="pending",
            )
            db.add(request)
            job.clarification_round = next_round
            job.status = "waiting_user"
            job.progress = max(job.progress, 5)
            job.error_code = None
            job.error_message = None
            db.add(JobEvent(
                job_id=job.id,
                event_type="clarification_needed",
                message="研究范围需要用户补充后才能继续。",
                progress=job.progress,
                level="info",
            ))
            await db.commit()
            return BriefValidationResult(ready=False, decision=decision)

        topic_spec = decision.topic_spec
        if topic_spec is None:
            # This is defensive for a future validator implementation; it preserves the
            # narrow-scope guarantee after the two-round cap.
            topic_spec = conservative_topic_spec(query, prompt_history)
        job.topic_spec = topic_spec.model_dump(mode="json")
        db.add(JobEvent(
            job_id=job.id,
            event_type="scope_confirmed",
            message="研究范围已确认，准备进入现有分析图。",
            progress=max(job.progress, 5),
            level="info",
        ))
        await db.commit()
        return BriefValidationResult(ready=True, topic_spec=topic_spec, decision=decision)
