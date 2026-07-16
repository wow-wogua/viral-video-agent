"""Database persistence and owned API serialization for P0-B snapshots."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    CrawlRun,
    CrawlRunCreatorObservation,
    CrawlRunVideo,
    CreatorRecord,
    SearchPageRecord,
    VideoRecord,
)
from src.intelligence.search_service import SearchSnapshotBundle


async def _upsert_creator(db: AsyncSession, creator) -> None:
    record = await db.get(CreatorRecord, creator.mid)
    if record is None:
        db.add(CreatorRecord(
            mid=creator.mid,
            name=creator.name,
            profile_url=creator.profile_url,
            avatar_url=creator.avatar_url,
            follower_count=creator.follower_count,
            observed_at=creator.observed_at,
            provider_name=creator.provider_name,
            provider_version=creator.provider_version,
            recent_sample_availability=creator.recent_sample_availability.value,
            recent_sample_count=creator.recent_sample_count,
            missing_reason=creator.missing_reason,
        ))
        return
    record.name = creator.name
    record.profile_url = creator.profile_url
    record.avatar_url = creator.avatar_url
    record.follower_count = creator.follower_count
    record.observed_at = creator.observed_at
    record.provider_name = creator.provider_name
    record.provider_version = creator.provider_version
    record.recent_sample_availability = creator.recent_sample_availability.value
    record.recent_sample_count = creator.recent_sample_count
    record.missing_reason = creator.missing_reason


async def _upsert_video(db: AsyncSession, video) -> None:
    record = await db.get(VideoRecord, video.bvid)
    values = {
        "aid": video.aid,
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
        db.add(VideoRecord(bvid=video.bvid, **values))
        return
    for name, value in values.items():
        setattr(record, name, value)


async def persist_search_snapshot(
    db: AsyncSession,
    job_id: uuid.UUID,
    bundle: SearchSnapshotBundle,
) -> CrawlRun:
    """Atomically replace one job's snapshot while preserving its crawl_run identity."""

    contract = bundle.crawl_run
    run = await db.scalar(select(CrawlRun).where(CrawlRun.job_id == job_id))
    if run is None:
        run = CrawlRun(id=uuid.UUID(contract.crawl_run_id), job_id=job_id)
        db.add(run)
    else:
        await db.execute(delete(CrawlRunCreatorObservation).where(CrawlRunCreatorObservation.crawl_run_id == run.id))
        await db.execute(delete(CrawlRunVideo).where(CrawlRunVideo.crawl_run_id == run.id))
        await db.execute(delete(SearchPageRecord).where(SearchPageRecord.crawl_run_id == run.id))

    run.schema_version = contract.schema_version
    run.keyword = contract.request.keyword
    run.requested_pages = contract.coverage.requested_pages
    run.successful_pages = contract.coverage.successful_pages
    run.raw_result_count = contract.coverage.raw_result_count
    run.deduplicated_video_count = contract.coverage.deduplicated_video_count
    run.candidate_creator_count = contract.coverage.candidate_creator_count
    run.provider_name = contract.provider.provider_name
    run.provider_version = contract.provider.provider_version
    run.sort_mode = contract.request.sort_mode.value
    run.time_range = contract.request.time_range.value
    run.partition = contract.request.partition
    run.filters = contract.request.filters
    run.status = contract.status.value
    run.partial_success = contract.coverage.partial_success
    run.truncation_reason = contract.coverage.truncation_reason
    run.coverage = contract.coverage.model_dump(mode="json")
    run.started_at = contract.started_at
    run.completed_at = contract.completed_at

    for creator in bundle.creators:
        await _upsert_creator(db, creator)
    await db.flush()
    for video in bundle.videos:
        await _upsert_video(db, video)
    await db.flush()

    for page in contract.pages:
        db.add(SearchPageRecord(
            crawl_run_id=run.id,
            page_number=page.page_number,
            status=page.status.value,
            requested_at=page.requested_at,
            completed_at=page.completed_at,
            request_duration_ms=page.request_duration_ms,
            source_url=page.source_url,
            raw_result_count=page.raw_result_count,
            normalized_result_count=page.normalized_result_count,
            provider_name=page.provider_name,
            provider_version=page.provider_version,
            native_filters=page.native_filters,
            local_filters=page.local_filters,
            raw_payload_hash=page.raw_payload_hash,
            error_code=page.error_code,
            error_summary=page.error_summary,
        ))
    for creator in bundle.creators:
        db.add(CrawlRunCreatorObservation(
            crawl_run_id=run.id,
            mid=creator.mid,
            name=creator.name,
            profile_url=creator.profile_url,
            avatar_url=creator.avatar_url,
            follower_count=creator.follower_count,
            observed_at=creator.observed_at,
            provider_name=creator.provider_name,
            provider_version=creator.provider_version,
            recent_sample_availability=creator.recent_sample_availability.value,
            recent_sample_count=creator.recent_sample_count,
            missing_reason=creator.missing_reason,
        ))
    for video in bundle.videos:
        db.add(CrawlRunVideo(
            crawl_run_id=run.id,
            bvid=video.bvid,
            page_number=video.source_page,
            result_rank=video.source_rank,
            aid=video.aid,
            creator_mid=video.creator_mid,
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
            relevance_label="uncertain",
            relevance_evidence_ids=[],
            raw_payload_hash=video.raw_payload_hash,
        ))
    await db.flush()
    return run


async def get_search_snapshot(db: AsyncSession, job_id: uuid.UUID) -> dict[str, Any] | None:
    run = await db.scalar(select(CrawlRun).where(CrawlRun.job_id == job_id))
    if run is None:
        return None
    pages = list((await db.scalars(
        select(SearchPageRecord)
        .where(SearchPageRecord.crawl_run_id == run.id)
        .order_by(SearchPageRecord.page_number)
    )).all())
    videos = list((await db.scalars(
        select(CrawlRunVideo)
        .where(CrawlRunVideo.crawl_run_id == run.id)
        .order_by(CrawlRunVideo.page_number, CrawlRunVideo.result_rank)
    )).all())
    creators = list((await db.scalars(
        select(CrawlRunCreatorObservation)
        .where(CrawlRunCreatorObservation.crawl_run_id == run.id)
        .order_by(CrawlRunCreatorObservation.mid)
    )).all())
    return {
        "crawl_run_id": run.id,
        "schema_version": run.schema_version,
        "keyword": run.keyword,
        "provider_name": run.provider_name,
        "provider_version": run.provider_version,
        "sort_mode": run.sort_mode,
        "time_range": run.time_range,
        "partition": run.partition,
        "filters": run.filters,
        "status": run.status,
        "partial_success": run.partial_success,
        "truncation_reason": run.truncation_reason,
        "coverage": run.coverage,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "pages": [{
            "page_number": page.page_number,
            "status": page.status,
            "requested_at": page.requested_at,
            "completed_at": page.completed_at,
            "request_duration_ms": page.request_duration_ms,
            "source_url": page.source_url,
            "raw_result_count": page.raw_result_count,
            "normalized_result_count": page.normalized_result_count,
            "provider_name": page.provider_name,
            "provider_version": page.provider_version,
            "native_filters": page.native_filters,
            "local_filters": page.local_filters,
            "raw_payload_hash": page.raw_payload_hash,
            "error_code": page.error_code,
            "error_summary": page.error_summary,
        } for page in pages],
        "videos": [{
            "bvid": observation.bvid,
            "aid": observation.aid,
            "creator_mid": observation.creator_mid,
            "creator_name": observation.creator_name,
            "title": observation.title,
            "description": observation.description,
            "tags": observation.tags,
            "partition": observation.partition,
            "published_at": observation.published_at,
            "duration_seconds": observation.duration_seconds,
            "cover_url": observation.cover_url,
            "source_url": observation.source_url,
            "view": observation.view,
            "like": observation.like,
            "coin": observation.coin,
            "favorite": observation.favorite,
            "reply": observation.reply,
            "share": observation.share,
            "danmaku": observation.danmaku,
            "observed_at": observation.observed_at,
            "provider_name": observation.provider_name,
            "provider_version": observation.provider_version,
            "missing_fields": observation.missing_fields,
            "source_page": observation.page_number,
            "source_rank": observation.result_rank,
            "raw_payload_hash": observation.raw_payload_hash,
        } for observation in videos],
        "creators": [{
            "mid": creator.mid,
            "name": creator.name,
            "profile_url": creator.profile_url,
            "avatar_url": creator.avatar_url,
            "follower_count": creator.follower_count,
            "observed_at": creator.observed_at,
            "provider_name": creator.provider_name,
            "provider_version": creator.provider_version,
            "recent_sample_availability": creator.recent_sample_availability,
            "recent_sample_count": creator.recent_sample_count,
            "missing_reason": creator.missing_reason,
        } for creator in creators],
    }
