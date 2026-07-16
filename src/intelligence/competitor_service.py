"""P0-C orchestration from a frozen search snapshot to deterministic competitors."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.intelligence.competitor_scoring import (
    MAX_CREATOR_AUDITS,
    CandidateCreator,
    ScoringInput,
    aggregate_candidates,
    rank_creator_audits,
    score_creator,
    select_top_competitors,
)
from src.intelligence.contracts import (
    CompetitorScore,
    CreatorSample,
    CreatorSampleStatus,
    CreatorSemanticAssessment,
    RelevanceDecision,
)
from src.intelligence.creator_providers import CreatorProvider
from src.intelligence.providers import CancelCheck
from src.intelligence.relevance import (
    CreatorLabelingResult,
    RelevanceContext,
    RelevanceLabeler,
    uncertain_creator_result,
)
from src.intelligence.search_service import SearchSnapshotBundle


@dataclass(slots=True)
class CreatorAnalysis:
    candidate: CandidateCreator
    sample: CreatorSample
    search_decisions: list[RelevanceDecision]
    sample_decisions: list[RelevanceDecision]
    assessment: CreatorSemanticAssessment
    search_evidence_ids: list[str]
    sample_evidence_ids: list[str]
    audited: bool


@dataclass(slots=True)
class CompetitorAnalysisBundle:
    crawl_run_id: str
    scoring_version: str
    generated_at: datetime
    candidate_creator_count: int
    audited_creator_count: int
    missing_mid_video_count: int
    scores: list[CompetitorScore]
    creator_analyses: dict[str, CreatorAnalysis]
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    shortfall_reason: str | None = None

    @property
    def selected_scores(self) -> list[CompetitorScore]:
        return sorted(
            (score for score in self.scores if score.selected),
            key=lambda score: score.selection_rank or 99,
        )


def _evidence_id(kind: str, crawl_run_id: str, creator_mid: str, identity: str) -> str:
    payload = f"{kind}|{crawl_run_id}|{creator_mid}|{identity}"
    return f"ev_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _search_evidence(bundle: SearchSnapshotBundle) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    evidence_by_bvid: dict[str, list[str]] = {}
    evidence_items = []
    for video in bundle.videos:
        if not video.creator_mid:
            continue
        evidence_id = _evidence_id("p0c-search-video", bundle.crawl_run.crawl_run_id, video.creator_mid, video.bvid)
        evidence_by_bvid.setdefault(video.bvid, []).append(evidence_id)
        evidence_items.append({
            "evidence_id": evidence_id,
            "tool": "p0c_search_snapshot",
            "source_type": "bilibili_search_video",
            "title": video.title,
            "source_url": video.source_url,
            "platform": "bilibili",
            "fetched_at": video.observed_at,
            "raw_data": {
                "bvid": video.bvid,
                "creator_mid": video.creator_mid,
                "provider_name": video.provider_name,
                "provider_version": video.provider_version,
                "source_page": video.source_page,
                "source_rank": video.source_rank,
                "raw_payload_hash": video.raw_payload_hash,
            },
            "summary": video.title[:300],
            "data_fields": {
                "view": video.view,
                "like": video.like,
                "favorite": video.favorite,
                "reply": video.reply,
                "danmaku": video.danmaku,
                "published_at": video.published_at.isoformat() if video.published_at else None,
            },
            "transcript_segment": None,
        })
    return evidence_by_bvid, evidence_items


def _sample_evidence(
    crawl_run_id: str,
    sample: CreatorSample,
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    evidence_by_bvid: dict[str, list[str]] = {}
    evidence_items = []
    for video in sample.uploads:
        evidence_id = _evidence_id("p0c-creator-upload", crawl_run_id, sample.creator_mid, video.bvid)
        evidence_by_bvid.setdefault(video.bvid, []).append(evidence_id)
        evidence_items.append({
            "evidence_id": evidence_id,
            "tool": "p0c_creator_provider",
            "source_type": "bilibili_creator_upload",
            "title": video.title,
            "source_url": video.source_url,
            "platform": "bilibili",
            "fetched_at": video.observed_at,
            "raw_data": {
                "bvid": video.bvid,
                "creator_mid": sample.creator_mid,
                "provider_name": sample.provider_name,
                "provider_version": sample.provider_version,
                "source_provider_name": sample.source_provider_name,
                "source_provider_version": sample.source_provider_version,
                "sample_rank": video.sample_rank,
                "raw_payload_hash": video.raw_payload_hash,
            },
            "summary": video.title[:300],
            "data_fields": {
                "view": video.view,
                "like": video.like,
                "favorite": video.favorite,
                "reply": video.reply,
                "danmaku": video.danmaku,
                "published_at": video.published_at.isoformat() if video.published_at else None,
            },
            "transcript_segment": None,
        })
    return evidence_by_bvid, evidence_items


def _missing_sample(candidate: CandidateCreator, provider: CreatorProvider, reason: str) -> CreatorSample:
    capabilities = provider.capabilities
    profile_url = f"https://space.bilibili.com/{candidate.creator_mid}"
    return CreatorSample(
        creator_mid=candidate.creator_mid,
        creator_name=candidate.creator_name,
        profile_url=profile_url,
        status=CreatorSampleStatus.MISSING,
        observed_at=datetime.now(timezone.utc),
        provider_name=capabilities.provider_name,
        provider_version=capabilities.provider_version,
        provider_kind=capabilities.provider_kind,
        source_provider_name=capabilities.provider_name,
        source_provider_version=capabilities.provider_version,
        source_url=profile_url,
        missing_reason=reason,
    )


def _combine_videos(candidate: CandidateCreator, sample: CreatorSample) -> list[Any]:
    combined: dict[str, Any] = {video.bvid: video for video in candidate.search_videos}
    for video in sample.uploads:
        combined[video.bvid] = video
    return list(combined.values())


def _split_decisions(
    result: CreatorLabelingResult,
    candidate: CandidateCreator,
    sample: CreatorSample,
) -> tuple[list[RelevanceDecision], list[RelevanceDecision]]:
    by_bvid = {decision.bvid: decision for decision in result.decisions}
    search = [by_bvid[video.bvid] for video in candidate.search_videos]
    uploads = [by_bvid[video.bvid] for video in sample.uploads]
    return search, uploads


async def analyze_competitors(
    bundle: SearchSnapshotBundle,
    creator_provider: CreatorProvider,
    labeler: RelevanceLabeler,
    context: RelevanceContext,
    *,
    cancel_check: CancelCheck | None = None,
    max_creator_audits: int = MAX_CREATOR_AUDITS,
) -> CompetitorAnalysisBundle:
    if not 1 <= max_creator_audits <= MAX_CREATOR_AUDITS:
        raise ValueError(f"max_creator_audits must be between 1 and {MAX_CREATOR_AUDITS}")
    candidates = aggregate_candidates(bundle.videos)
    audit_order = rank_creator_audits(candidates, context)
    audited_mids = {candidate.creator_mid for candidate in audit_order[:max_creator_audits]}
    search_evidence_by_bvid, evidence_items = _search_evidence(bundle)
    analyses: dict[str, CreatorAnalysis] = {}

    for candidate in audit_order:
        if cancel_check and await cancel_check():
            sample = _missing_sample(candidate, creator_provider, "cancelled_before_creator_audit")
            combined = _combine_videos(candidate, sample)
            result = uncertain_creator_result(
                combined,
                search_evidence_by_bvid,
                reason="creator audit cancelled",
            )
            search_decisions, sample_decisions = _split_decisions(result, candidate, sample)
            analyses[candidate.creator_mid] = CreatorAnalysis(
                candidate, sample, search_decisions, sample_decisions, result.assessment,
                [item for video in candidate.search_videos for item in search_evidence_by_bvid.get(video.bvid, [])],
                [], False,
            )
            continue

        if candidate.creator_mid not in audited_mids:
            sample = _missing_sample(candidate, creator_provider, "not_audited_due_to_fixed_limit")
            result = uncertain_creator_result(
                candidate.search_videos,
                search_evidence_by_bvid,
                reason="creator was outside the fixed audit limit",
            )
            analyses[candidate.creator_mid] = CreatorAnalysis(
                candidate=candidate,
                sample=sample,
                search_decisions=result.decisions,
                sample_decisions=[],
                assessment=result.assessment,
                search_evidence_ids=[
                    item for video in candidate.search_videos for item in search_evidence_by_bvid.get(video.bvid, [])
                ],
                sample_evidence_ids=[],
                audited=False,
            )
            continue

        sample = await creator_provider.fetch_creator(
            candidate.creator_mid,
            candidate.creator_name,
            cancel_check,
        )
        sample_evidence_by_bvid, new_evidence = _sample_evidence(bundle.crawl_run.crawl_run_id, sample)
        evidence_items.extend(new_evidence)
        combined_evidence = {
            bvid: list(dict.fromkeys([
                *search_evidence_by_bvid.get(bvid, []),
                *sample_evidence_by_bvid.get(bvid, []),
            ]))
            for bvid in set(search_evidence_by_bvid) | set(sample_evidence_by_bvid)
        }
        combined_videos = _combine_videos(candidate, sample)
        result = await labeler.label_creator(
            context,
            candidate.creator_mid,
            candidate.creator_name,
            combined_videos,
            combined_evidence,
        )
        search_decisions, sample_decisions = _split_decisions(result, candidate, sample)
        analyses[candidate.creator_mid] = CreatorAnalysis(
            candidate=candidate,
            sample=sample,
            search_decisions=search_decisions,
            sample_decisions=sample_decisions,
            assessment=result.assessment,
            search_evidence_ids=[
                item for video in candidate.search_videos for item in search_evidence_by_bvid.get(video.bvid, [])
            ],
            sample_evidence_ids=[
                item for video in sample.uploads for item in sample_evidence_by_bvid.get(video.bvid, [])
            ],
            audited=True,
        )

    scores = [
        score_creator(ScoringInput(
            candidate=analysis.candidate,
            creator_sample=analysis.sample,
            search_decisions=analysis.search_decisions,
            sample_decisions=analysis.sample_decisions,
            assessment=analysis.assessment,
            search_evidence_ids=analysis.search_evidence_ids,
            sample_evidence_ids=analysis.sample_evidence_ids,
        ), context)
        for analysis in analyses.values()
    ]
    selected_scores, shortfall_reason = select_top_competitors(scores)
    return CompetitorAnalysisBundle(
        crawl_run_id=bundle.crawl_run.crawl_run_id,
        scoring_version=selected_scores[0].scoring_version if selected_scores else "competitor-score.p0.1",
        generated_at=datetime.now(timezone.utc),
        candidate_creator_count=len(candidates),
        audited_creator_count=sum(analysis.audited for analysis in analyses.values()),
        missing_mid_video_count=sum(video.creator_mid is None for video in bundle.videos),
        scores=selected_scores,
        creator_analyses=analyses,
        evidence_items=evidence_items,
        shortfall_reason=shortfall_reason,
    )
