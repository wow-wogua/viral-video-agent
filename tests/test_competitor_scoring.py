from datetime import datetime, timedelta, timezone

import pytest

from src.intelligence.competitor_scoring import (
    COMPONENT_WEIGHTS,
    PENALTY_CAP,
    CandidateCreator,
    ScoringInput,
    aggregate_candidates,
    rank_creator_audits,
    score_creator,
    select_top_competitors,
)
from src.intelligence.contracts import (
    CreatorQualificationStatus,
    CreatorSample,
    CreatorSampleStatus,
    CreatorSemanticAssessment,
    CreatorVideo,
    RelevanceDecision,
    RelevanceLabel,
    Video,
)
from src.intelligence.relevance import RelevanceContext


NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)
CONTEXT = RelevanceContext(keyword="sanitized topic", category="vertical")


def search_video(index: int, *, mid="90001", view=10000, rank=None) -> Video:
    return Video(
        bvid=f"BV{index:010d}",
        creator_mid=mid,
        creator_name=f"creator-{mid}",
        title="sanitized topic search result",
        description="sanitized topic",
        tags=["sanitized topic"],
        published_at=NOW - timedelta(days=index),
        source_url=f"https://www.bilibili.com/video/BV{index:010d}",
        view=view,
        like=500,
        favorite=200,
        reply=80,
        danmaku=40,
        observed_at=NOW,
        provider_name="fixture-search",
        provider_version="fixture-search-v1",
        source_page=1,
        source_rank=rank or index,
        missing_fields=["coin", "share"],
    )


def creator_video(index: int, *, mid="90001", days=10, complete_interaction=True) -> CreatorVideo:
    return CreatorVideo(
        bvid=f"BV{index:010d}",
        creator_mid=mid,
        creator_name=f"creator-{mid}",
        title="sanitized topic creator upload",
        description="sanitized topic",
        tags=["sanitized topic"],
        published_at=NOW - timedelta(days=days),
        source_url=f"https://www.bilibili.com/video/BV{index:010d}",
        view=10000,
        like=500 if complete_interaction else None,
        favorite=200 if complete_interaction else None,
        reply=80 if complete_interaction else None,
        danmaku=40 if complete_interaction else None,
        observed_at=NOW,
        provider_name="fixture-creator",
        provider_version="fixture-creator-v1",
        sample_rank=index - 100,
        missing_fields=[] if complete_interaction else ["like", "favorite", "reply", "danmaku"],
    )


def decision(bvid: str, label=RelevanceLabel.RELEVANT, confidence=0.9) -> RelevanceDecision:
    return RelevanceDecision(
        bvid=bvid,
        label=label,
        reason="fixture semantic decision",
        confidence=confidence,
        evidence_ids=[f"ev_{bvid[-8:]}"],
        labeler="fixture",
        labeler_version="content-relevance.p0.1",
    )


def scoring_input(
    *,
    mid="90001",
    search_count=3,
    sample_count=10,
    relevant_count=10,
    recent_days=10,
    follower_count=20000,
    status=CreatorSampleStatus.SUCCESS,
    complete_interaction=True,
    assessment_confidence=0.9,
    risk_flags=None,
) -> ScoringInput:
    search = [search_video(index, mid=mid) for index in range(1, search_count + 1)]
    uploads = [
        creator_video(101 + index, mid=mid, days=recent_days + index, complete_interaction=complete_interaction)
        for index in range(sample_count)
    ]
    sample = CreatorSample(
        creator_mid=mid,
        creator_name=f"creator-{mid}",
        profile_url=f"https://example.test/{mid}",
        status=status,
        observed_at=NOW,
        provider_name="fixture",
        provider_version="fixture-v1",
        provider_kind="fixture",
        source_provider_name="fixture-source",
        source_provider_version="fixture-source-v1",
        source_url=f"https://example.test/{mid}/uploads",
        follower_count=follower_count,
        uploads=uploads,
        recent_30d_upload_count=sum(video.published_at >= NOW - timedelta(days=30) for video in uploads),
        recent_90d_upload_count=sum(video.published_at >= NOW - timedelta(days=90) for video in uploads),
        missing_reason=None if status == CreatorSampleStatus.SUCCESS else "fixture sample unavailable or partial",
    )
    sample_labels = [
        decision(video.bvid, RelevanceLabel.RELEVANT if index < relevant_count else RelevanceLabel.IRRELEVANT)
        for index, video in enumerate(uploads)
    ]
    return ScoringInput(
        candidate=CandidateCreator(mid, f"creator-{mid}", search),
        creator_sample=sample,
        search_decisions=[decision(video.bvid) for video in search],
        sample_decisions=sample_labels,
        assessment=CreatorSemanticAssessment(
            generalist=False,
            risk_flags=risk_flags or [],
            reason="fixture assessment",
            confidence=assessment_confidence,
            labeler="fixture",
            labeler_version="content-relevance.p0.1",
        ),
        search_evidence_ids=[f"ev_search_{mid}"],
        sample_evidence_ids=[f"ev_sample_{mid}"],
    )


def test_component_weights_sum_to_one_hundred_and_each_positive_component_scores():
    assert sum(COMPONENT_WEIGHTS.values()) == 100
    score = score_creator(scoring_input(), CONTEXT)
    assert set(score.component_scores) == set(COMPONENT_WEIGHTS)
    assert all(value > 0 for value in score.component_scores.values())
    assert score.qualification_status == CreatorQualificationStatus.QUALIFIED_REFERENCE


def test_missing_uploads_have_explicit_penalties_and_low_confidence():
    value = scoring_input(sample_count=0, relevant_count=0, status=CreatorSampleStatus.MISSING)
    score = score_creator(value, CONTEXT)
    assert score.penalty_scores["missing_upload_list"] == 5
    assert score.component_details["recent_relevant_ratio"].missing_reason
    assert score.confidence < 0.3
    assert score.qualification_status == CreatorQualificationStatus.DISCOVERY_ONLY


def test_single_hit_inactive_and_small_sample_penalties_are_deterministic():
    value = scoring_input(search_count=1, sample_count=2, relevant_count=1, recent_days=100)
    score = score_creator(value, CONTEXT)
    assert score.penalty_scores["single_hit_without_continuity"] == 5
    assert score.penalty_scores["inactive_90d"] == 5
    assert score.penalty_scores["insufficient_sample"] == 4


def test_missing_interaction_fields_are_not_silently_filled():
    value = scoring_input(complete_interaction=False)
    for video in value.candidate.search_videos:
        video.like = video.favorite = video.reply = video.danmaku = None
    score = score_creator(value, CONTEXT)
    detail = score.component_details["interaction_performance"]
    assert detail.score == 0
    assert detail.denominator is None
    assert detail.missing_reason
    assert score.penalty_scores["missing_interaction_fields"] == 2


def test_total_score_and_penalty_boundaries_hold_under_multiple_failures():
    value = scoring_input(
        search_count=1,
        sample_count=3,
        relevant_count=0,
        recent_days=120,
        follower_count=None,
        status=CreatorSampleStatus.PARTIAL,
        complete_interaction=False,
        assessment_confidence=0.2,
        risk_flags=["content_farm", "occasional_hit"],
    )
    score = score_creator(value, CONTEXT)
    assert 0 <= score.total_score <= 100
    assert sum(score.penalty_scores.values()) <= PENALTY_CAP


def test_low_result_never_uses_the_standard_qualification_policy():
    score = score_creator(scoring_input(), RelevanceContext(keyword="sanitized", category="low_result"))
    assert score.qualification_status == CreatorQualificationStatus.DISCOVERY_ONLY


def test_stable_sort_and_tie_break_ignore_input_order():
    first = score_creator(scoring_input(mid="90001"), CONTEXT)
    second = score_creator(scoring_input(mid="90002"), CONTEXT)
    forward, _ = select_top_competitors([second, first])
    reverse, _ = select_top_competitors([first, second])
    assert [(item.creator_mid, item.selection_rank) for item in forward] == [
        (item.creator_mid, item.selection_rank) for item in reverse
    ]
    assert [item.creator_mid for item in forward if item.selected] == ["90001", "90002"]


def test_fewer_than_five_and_zero_qualified_creators_are_not_padded():
    qualified = score_creator(scoring_input(), CONTEXT)
    selected, shortfall = select_top_competitors([qualified])
    assert sum(item.selected for item in selected) == 1
    assert shortfall
    emerging_input = scoring_input(follower_count=100, mid="90002")
    for video in emerging_input.creator_sample.uploads:
        video.view = 1000
    emerging = score_creator(emerging_input, CONTEXT)
    selected, shortfall = select_top_competitors([emerging])
    assert sum(item.selected for item in selected) == 0
    assert shortfall


def test_candidate_aggregation_and_audit_ranking_are_input_order_independent():
    videos = [search_video(3, mid="90002"), search_video(1, mid="90001"), search_video(2, mid="90001")]
    forward = rank_creator_audits(aggregate_candidates(videos), CONTEXT)
    reverse = rank_creator_audits(aggregate_candidates(list(reversed(videos))), CONTEXT)
    assert [item.creator_mid for item in forward] == [item.creator_mid for item in reverse]
    assert forward[0].creator_mid == "90001"
