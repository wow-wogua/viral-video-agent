"""Atomic persistence and owned serialization for P0-C results."""

from __future__ import annotations

import uuid
from datetime import timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    CompetitorScoreRecord,
    CrawlRun,
    CrawlRunVideo,
    CreatorAuditRecord,
    CreatorRecord,
    CreatorSampleVideoRecord,
    EvidenceItem,
    VideoRecord,
)
from src.intelligence.competitor_service import CompetitorAnalysisBundle
from src.intelligence.snapshots import IMMUTABLE_SNAPSHOT_REVISION


async def _upsert_sample_creator(db: AsyncSession, analysis) -> None:
    sample = analysis.sample
    record = await db.get(CreatorRecord, sample.creator_mid)
    if record is None:
        db.add(CreatorRecord(
            mid=sample.creator_mid,
            name=sample.creator_name,
            profile_url=sample.profile_url,
            follower_count=sample.follower_count,
            observed_at=sample.observed_at,
            provider_name=sample.provider_name,
            provider_version=sample.provider_version,
            recent_sample_availability=(
                "available" if sample.status.value == "success"
                else "partial" if sample.uploads
                else "missing"
            ),
            recent_sample_count=len(sample.uploads),
            missing_reason=sample.missing_reason,
        ))
        return
    if sample.creator_name:
        record.name = sample.creator_name
    record.profile_url = sample.profile_url
    if sample.follower_count is not None:
        record.follower_count = sample.follower_count
    record_observed_at = record.observed_at
    if record_observed_at.tzinfo is None:
        record_observed_at = record_observed_at.replace(tzinfo=timezone.utc)
    if sample.observed_at >= record_observed_at:
        record.observed_at = sample.observed_at
        record.provider_name = sample.provider_name
        record.provider_version = sample.provider_version
        record.recent_sample_availability = (
            "available" if sample.status.value == "success"
            else "partial" if sample.uploads
            else "missing"
        )
        record.recent_sample_count = len(sample.uploads)
        record.missing_reason = sample.missing_reason


async def _upsert_sample_video(db: AsyncSession, video) -> None:
    record = await db.get(VideoRecord, video.bvid)
    values = {
        "creator_mid": video.creator_mid,
        "creator_name": video.creator_name,
        "title": video.title,
        "description": video.description,
        "tags": video.tags,
        "partition": video.partition,
        "published_at": video.published_at,
        "duration_seconds": video.duration_seconds,
        "cover_url": video.cover_url,
        "source_url": video.source_url,
        "view": video.view,
        "like": video.like,
        "coin": video.coin,
        "favorite": video.favorite,
        "reply": video.reply,
        "share": video.share,
        "danmaku": video.danmaku,
        "observed_at": video.observed_at,
        "provider_name": video.provider_name,
        "provider_version": video.provider_version,
        "missing_fields": video.missing_fields,
    }
    if record is None:
        db.add(VideoRecord(bvid=video.bvid, aid=None, **values))
        return
    for name, value in values.items():
        if value is not None and (name != "tags" or value):
            setattr(record, name, value)


async def persist_competitor_analysis(
    db: AsyncSession,
    job_id: uuid.UUID,
    analysis_bundle: CompetitorAnalysisBundle,
) -> CrawlRun:
    run = await db.scalar(select(CrawlRun).where(CrawlRun.job_id == job_id))
    if run is None or str(run.id) != analysis_bundle.crawl_run_id:
        raise ValueError("competitor analysis crawl run does not match the job snapshot")
    if run.snapshot_revision != IMMUTABLE_SNAPSHOT_REVISION:
        raise ValueError("P0-C requires a crawl run created after immutable snapshot revision 20260716_0003")

    await db.execute(delete(EvidenceItem).where(EvidenceItem.crawl_run_id == run.id, EvidenceItem.report_id.is_(None)))
    await db.execute(delete(CompetitorScoreRecord).where(CompetitorScoreRecord.crawl_run_id == run.id))
    await db.execute(delete(CreatorSampleVideoRecord).where(CreatorSampleVideoRecord.crawl_run_id == run.id))
    await db.execute(delete(CreatorAuditRecord).where(CreatorAuditRecord.crawl_run_id == run.id))

    score_by_mid = {score.creator_mid: score for score in analysis_bundle.scores}
    for creator_analysis in analysis_bundle.creator_analyses.values():
        await _upsert_sample_creator(db, creator_analysis)
    await db.flush()
    for creator_analysis in analysis_bundle.creator_analyses.values():
        for video in creator_analysis.sample.uploads:
            await _upsert_sample_video(db, video)
    await db.flush()

    search_observations = list((await db.scalars(
        select(CrawlRunVideo).where(CrawlRunVideo.crawl_run_id == run.id)
    )).all())
    search_decisions = {
        decision.bvid: decision
        for creator_analysis in analysis_bundle.creator_analyses.values()
        for decision in creator_analysis.search_decisions
    }
    for observation in search_observations:
        decision = search_decisions.get(observation.bvid)
        if decision is None:
            continue
        observation.relevance_label = decision.label.value
        observation.relevance_reason = decision.reason
        observation.relevance_confidence = decision.confidence
        observation.relevance_evidence_ids = decision.evidence_ids
        observation.relevance_labeler = decision.labeler
        observation.relevance_labeler_version = decision.labeler_version

    for creator_analysis in analysis_bundle.creator_analyses.values():
        sample = creator_analysis.sample
        score = score_by_mid[creator_analysis.candidate.creator_mid]
        evidence_ids = list(dict.fromkeys([
            *creator_analysis.search_evidence_ids,
            *creator_analysis.sample_evidence_ids,
        ]))
        db.add(CreatorAuditRecord(
            crawl_run_id=run.id,
            creator_mid=sample.creator_mid,
            creator_name=sample.creator_name,
            profile_url=sample.profile_url,
            status=sample.status.value,
            observed_at=sample.observed_at,
            provider_name=sample.provider_name,
            provider_version=sample.provider_version,
            provider_kind=sample.provider_kind,
            source_provider_name=sample.source_provider_name,
            source_provider_version=sample.source_provider_version,
            source_url=sample.source_url,
            follower_count=sample.follower_count,
            sample_count=len(sample.uploads),
            recent_30d_upload_count=sample.recent_30d_upload_count,
            recent_90d_upload_count=sample.recent_90d_upload_count,
            qualification_status=score.qualification_status.value,
            generalist=creator_analysis.assessment.generalist,
            risk_flags=creator_analysis.assessment.risk_flags,
            assessment_reason=creator_analysis.assessment.reason,
            assessment_confidence=creator_analysis.assessment.confidence,
            missing_reason=sample.missing_reason,
            evidence_ids=evidence_ids,
            raw_payload_hash=sample.raw_payload_hash,
        ))
        sample_decisions = {decision.bvid: decision for decision in creator_analysis.sample_decisions}
        for video in sample.uploads:
            decision = sample_decisions[video.bvid]
            db.add(CreatorSampleVideoRecord(
                crawl_run_id=run.id,
                creator_mid=sample.creator_mid,
                bvid=video.bvid,
                sample_rank=video.sample_rank,
                creator_name=video.creator_name,
                title=video.title,
                description=video.description,
                tags=video.tags,
                partition=video.partition,
                published_at=video.published_at,
                duration_seconds=video.duration_seconds,
                cover_url=video.cover_url,
                source_url=video.source_url,
                view=video.view,
                like=video.like,
                coin=video.coin,
                favorite=video.favorite,
                reply=video.reply,
                share=video.share,
                danmaku=video.danmaku,
                observed_at=video.observed_at,
                provider_name=video.provider_name,
                provider_version=video.provider_version,
                missing_fields=video.missing_fields,
                raw_payload_hash=video.raw_payload_hash,
                relevance_label=decision.label.value,
                relevance_reason=decision.reason,
                relevance_confidence=decision.confidence,
                relevance_evidence_ids=decision.evidence_ids,
                relevance_labeler=decision.labeler,
                relevance_labeler_version=decision.labeler_version,
            ))

    for score in analysis_bundle.scores:
        db.add(CompetitorScoreRecord(
            crawl_run_id=run.id,
            creator_mid=score.creator_mid,
            creator_name=score.creator_name,
            scoring_version=score.scoring_version,
            component_scores=score.component_scores,
            component_details={name: detail.model_dump(mode="json") for name, detail in score.component_details.items()},
            penalty_scores=score.penalty_scores,
            total_score=score.total_score,
            confidence=score.confidence,
            qualification_status=score.qualification_status.value,
            selected=score.selected,
            selection_rank=score.selection_rank,
            inclusion_reason=score.inclusion_reason,
            exclusion_reason=score.exclusion_reason,
            evidence_ids=score.evidence_ids,
            search_candidate_sources=score.search_candidate_sources,
            creator_sample_sources=score.creator_sample_sources,
            tie_break_values=score.tie_break_values,
            metric_results=[],
            created_at=analysis_bundle.generated_at,
        ))

    if run.job_id is None:
        raise ValueError("P0-C Evidence requires a job-owned crawl run")
    for item in analysis_bundle.evidence_items:
        db.add(EvidenceItem(
            job_id=run.job_id,
            crawl_run_id=run.id,
            report_id=None,
            **item,
        ))
    coverage = dict(run.coverage or {})
    coverage["actual_competitor_count"] = len(analysis_bundle.selected_scores)
    run.coverage = coverage
    await db.flush()
    return run


async def get_competitor_results(db: AsyncSession, job_id: uuid.UUID) -> dict[str, Any] | None:
    run = await db.scalar(select(CrawlRun).where(CrawlRun.job_id == job_id))
    if run is None:
        return None
    scores = list((await db.scalars(
        select(CompetitorScoreRecord)
        .where(CompetitorScoreRecord.crawl_run_id == run.id)
        .order_by(CompetitorScoreRecord.selected.desc(), CompetitorScoreRecord.selection_rank, CompetitorScoreRecord.total_score.desc(), CompetitorScoreRecord.creator_mid)
    )).all())
    if not scores:
        return None
    audits = list((await db.scalars(
        select(CreatorAuditRecord)
        .where(CreatorAuditRecord.crawl_run_id == run.id)
        .order_by(CreatorAuditRecord.creator_mid)
    )).all())
    sample_videos = list((await db.scalars(
        select(CreatorSampleVideoRecord)
        .where(CreatorSampleVideoRecord.crawl_run_id == run.id)
        .order_by(CreatorSampleVideoRecord.creator_mid, CreatorSampleVideoRecord.sample_rank)
    )).all())
    search_videos = list((await db.scalars(
        select(CrawlRunVideo)
        .where(CrawlRunVideo.crawl_run_id == run.id)
        .order_by(CrawlRunVideo.creator_mid, CrawlRunVideo.page_number, CrawlRunVideo.result_rank)
    )).all())
    evidence = list((await db.scalars(
        select(EvidenceItem)
        .where(EvidenceItem.crawl_run_id == run.id, EvidenceItem.report_id.is_(None))
        .order_by(EvidenceItem.evidence_id)
    )).all())
    audit_by_mid = {audit.creator_mid: audit for audit in audits}
    sample_by_mid: dict[str, list[CreatorSampleVideoRecord]] = {}
    for video in sample_videos:
        sample_by_mid.setdefault(video.creator_mid, []).append(video)
    search_by_mid: dict[str, list[CrawlRunVideo]] = {}
    for video in search_videos:
        if video.creator_mid:
            search_by_mid.setdefault(video.creator_mid, []).append(video)

    def label_payload(video) -> dict[str, Any]:
        return {
            "bvid": video.bvid,
            "title": video.title,
            "source_url": video.source_url,
            "published_at": video.published_at,
            "label": video.relevance_label,
            "reason": video.relevance_reason,
            "confidence": video.relevance_confidence,
            "evidence_ids": video.relevance_evidence_ids,
            "labeler": video.relevance_labeler,
            "labeler_version": video.relevance_labeler_version,
        }

    def score_payload(score: CompetitorScoreRecord) -> dict[str, Any]:
        audit = audit_by_mid.get(score.creator_mid)
        return {
            "creator_mid": score.creator_mid,
            "creator_name": score.creator_name,
            "total_score": score.total_score,
            "component_scores": score.component_scores,
            "component_details": score.component_details,
            "penalty_scores": score.penalty_scores,
            "confidence": score.confidence,
            "qualification_status": score.qualification_status,
            "selected": score.selected,
            "selection_rank": score.selection_rank,
            "inclusion_reason": score.inclusion_reason,
            "exclusion_reason": score.exclusion_reason,
            "search_candidate_sources": score.search_candidate_sources,
            "creator_sample_sources": score.creator_sample_sources,
            "evidence_ids": score.evidence_ids,
            "scoring_version": score.scoring_version,
            "tie_break_values": score.tie_break_values,
            "creator_sample": None if audit is None else {
                "status": audit.status,
                "profile_url": audit.profile_url,
                "observed_at": audit.observed_at,
                "provider_name": audit.provider_name,
                "provider_version": audit.provider_version,
                "provider_kind": audit.provider_kind,
                "source_provider_name": audit.source_provider_name,
                "source_provider_version": audit.source_provider_version,
                "source_url": audit.source_url,
                "follower_count": audit.follower_count,
                "sample_count": audit.sample_count,
                "recent_30d_upload_count": audit.recent_30d_upload_count,
                "recent_90d_upload_count": audit.recent_90d_upload_count,
                "generalist": audit.generalist,
                "risk_flags": audit.risk_flags,
                "assessment_reason": audit.assessment_reason,
                "assessment_confidence": audit.assessment_confidence,
                "missing_reason": audit.missing_reason,
            },
            "search_relevance_labels": [label_payload(video) for video in search_by_mid.get(score.creator_mid, [])],
            "creator_relevance_labels": [label_payload(video) for video in sample_by_mid.get(score.creator_mid, [])],
        }

    candidates = [score_payload(score) for score in scores]
    selected = sorted((item for item in candidates if item["selected"]), key=lambda item: item["selection_rank"])
    return {
        "crawl_run_id": run.id,
        "snapshot_revision": run.snapshot_revision,
        "scoring_version": scores[0].scoring_version,
        "keyword": run.keyword,
        "candidate_creator_count": len(scores),
        "audited_creator_count": sum(audit.status != "missing" or audit.missing_reason != "not_audited_due_to_fixed_limit" for audit in audits),
        "selected_count": len(selected),
        "shortfall_reason": None if len(selected) == 5 else f"only {len(selected)} qualified_reference creators were available; weak candidates were not used as filler",
        "selected": selected,
        "candidates": candidates,
        "evidence": [{
            "evidence_id": item.evidence_id,
            "tool": item.tool,
            "source_type": item.source_type,
            "title": item.title,
            "source_url": item.source_url,
            "platform": item.platform,
            "fetched_at": item.fetched_at,
            "data_fields": item.data_fields,
        } for item in evidence],
    }
