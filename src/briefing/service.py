from dataclasses import dataclass
import uuid

from sqlalchemy import select

from src.briefing.schemas import BriefDecision, TopicSpec
from src.briefing.validator import BriefValidator
from src.db.models import AnalysisJob, JobClarification, JobEvent
from src.db.session import async_session_factory
from src.gateway.cost_tracker import cost_tracker


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


async def validate_job_brief(job_id: uuid.UUID, validator: BriefValidator | None = None) -> BriefValidationResult:
    validator = validator or BriefValidator()
    async with async_session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        if not job:
            return BriefValidationResult(ready=False)
        if job.topic_spec:
            return BriefValidationResult(ready=True, topic_spec=TopicSpec.model_validate(job.topic_spec))

        history_rows = await _history(db, job_id)
        next_round = len(history_rows) + 1
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
        decision = await validator.validate(job.query, prompt_history, next_round)
        usage = _merge_usage(job.interaction_usage, cost_tracker.get_summary())
        job.interaction_usage = usage

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
            from src.briefing.validator import conservative_topic_spec

            topic_spec = conservative_topic_spec(job.query, prompt_history)
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
