"""Deterministic P0 metric formulas with explicit missing-data behavior."""

from __future__ import annotations

from collections.abc import Sequence
from statistics import median

from src.intelligence.contracts import MetricName, MetricResult, REPRESENTATIVE_VIDEO_TARGET, Video


SMALL_SAMPLE_THRESHOLD = 3
SMALL_SAMPLE_WARNING = "effective sample size is below 3"
NO_WINSORIZATION = "raw display value; no winsorization"


def _require_nonnegative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _warning(sample_size: int) -> str | None:
    return SMALL_SAMPLE_WARNING if sample_size < SMALL_SAMPLE_THRESHOLD else None


def _result(
    *,
    metric_name: MetricName,
    value: float | None,
    unit: str,
    numerator: float | None,
    denominator: float | None,
    sample_size: int,
    time_window: str,
    missing_rule: str,
    evidence_ids: Sequence[str],
    extreme_value_rule: str = NO_WINSORIZATION,
    warning_sample_size: int | None = None,
) -> MetricResult:
    if not evidence_ids:
        raise ValueError("metric results require at least one Evidence ID")
    return MetricResult(
        metric_name=metric_name,
        value=value,
        unit=unit,
        numerator=numerator,
        denominator=denominator,
        sample_size=sample_size,
        time_window=time_window,
        missing_rule=missing_rule,
        small_sample_warning=_warning(sample_size if warning_sample_size is None else warning_sample_size),
        extreme_value_rule=extreme_value_rule,
        evidence_ids=list(evidence_ids),
    )


def interaction_rate(video: Video, *, evidence_ids: Sequence[str]) -> MetricResult:
    fields = [video.like, video.coin, video.favorite, video.reply, video.share]
    complete = video.view is not None and video.view > 0 and all(value is not None for value in fields)
    numerator = float(sum(value for value in fields if value is not None)) if complete else None
    denominator = float(video.view) if video.view is not None else None
    value = numerator / denominator if complete and denominator is not None else None
    return _result(
        metric_name=MetricName.INTERACTION_RATE,
        value=value,
        unit="ratio",
        numerator=numerator,
        denominator=denominator,
        sample_size=1,
        time_window="video_observation",
        missing_rule="null when any interaction field is missing or view <= 0",
        evidence_ids=evidence_ids,
    )


def _single_video_rate(
    video: Video,
    *,
    metric_name: MetricName,
    numerator_value: int | None,
    numerator_name: str,
    evidence_ids: Sequence[str],
) -> MetricResult:
    complete = numerator_value is not None and video.view is not None and video.view > 0
    numerator = float(numerator_value) if numerator_value is not None else None
    denominator = float(video.view) if video.view is not None else None
    value = numerator / denominator if complete and denominator is not None else None
    return _result(
        metric_name=metric_name,
        value=value,
        unit="ratio",
        numerator=numerator,
        denominator=denominator,
        sample_size=1,
        time_window="video_observation",
        missing_rule=f"null when {numerator_name} is missing or view <= 0",
        evidence_ids=evidence_ids,
    )


def favorite_rate(video: Video, *, evidence_ids: Sequence[str]) -> MetricResult:
    return _single_video_rate(
        video,
        metric_name=MetricName.FAVORITE_RATE,
        numerator_value=video.favorite,
        numerator_name="favorite",
        evidence_ids=evidence_ids,
    )


def coin_rate(video: Video, *, evidence_ids: Sequence[str]) -> MetricResult:
    return _single_video_rate(
        video,
        metric_name=MetricName.COIN_RATE,
        numerator_value=video.coin,
        numerator_name="coin",
        evidence_ids=evidence_ids,
    )


def reply_rate(video: Video, *, evidence_ids: Sequence[str]) -> MetricResult:
    return _single_video_rate(
        video,
        metric_name=MetricName.REPLY_RATE,
        numerator_value=video.reply,
        numerator_name="reply",
        evidence_ids=evidence_ids,
    )


def posting_frequency(
    *,
    relevant_upload_count_30d: int | None,
    observed_upload_count_30d: int | None,
    recent_sample_available: bool,
    evidence_ids: Sequence[str],
) -> MetricResult:
    if relevant_upload_count_30d is not None:
        _require_nonnegative("relevant_upload_count_30d", relevant_upload_count_30d)
    if observed_upload_count_30d is not None:
        _require_nonnegative("observed_upload_count_30d", observed_upload_count_30d)
    if (
        relevant_upload_count_30d is not None
        and observed_upload_count_30d is not None
        and relevant_upload_count_30d > observed_upload_count_30d
    ):
        raise ValueError("relevant_upload_count_30d cannot exceed observed_upload_count_30d")
    available = (
        recent_sample_available
        and relevant_upload_count_30d is not None
        and observed_upload_count_30d is not None
    )
    numerator = float(relevant_upload_count_30d) if available else None
    denominator = 30.0 if available else None
    value = numerator / denominator * 7 if available and numerator is not None else None
    return _result(
        metric_name=MetricName.POSTING_FREQUENCY,
        value=value,
        unit="videos_per_week",
        numerator=numerator,
        denominator=denominator,
        sample_size=observed_upload_count_30d or 0,
        time_window="30d",
        missing_rule="null when the creator recent-upload sample is unavailable",
        evidence_ids=evidence_ids,
    )


def view_median(videos: Sequence[Video], *, evidence_ids: Sequence[str]) -> MetricResult:
    values = [video.view for video in videos if video.view is not None]
    value = float(median(values)) if values else None
    return _result(
        metric_name=MetricName.VIEW_MEDIAN,
        value=value,
        unit="views",
        numerator=None,
        denominator=None,
        sample_size=len(values),
        time_window="representative_sample",
        missing_rule="exclude missing view; view=0 remains a valid sample",
        evidence_ids=evidence_ids,
    )


def interaction_median(videos: Sequence[Video], *, evidence_ids: Sequence[str]) -> MetricResult:
    totals = []
    for video in videos:
        fields = [video.like, video.coin, video.favorite, video.reply, video.share]
        if all(value is not None for value in fields):
            totals.append(sum(value for value in fields if value is not None))
    value = float(median(totals)) if totals else None
    return _result(
        metric_name=MetricName.INTERACTION_MEDIAN,
        value=value,
        unit="interactions",
        numerator=None,
        denominator=None,
        sample_size=len(totals),
        time_window="representative_sample",
        missing_rule="exclude a video when any interaction field is missing",
        evidence_ids=evidence_ids,
    )


def viral_rate(videos: Sequence[Video], *, evidence_ids: Sequence[str]) -> MetricResult:
    views = [video.view for video in videos if video.view is not None]
    sample_size = len(views)
    if sample_size < SMALL_SAMPLE_THRESHOLD:
        return _result(
            metric_name=MetricName.VIRAL_RATE,
            value=None,
            unit="ratio",
            numerator=None,
            denominator=float(sample_size),
            sample_size=sample_size,
            time_window="representative_sample",
            missing_rule="null when fewer than 3 videos have a valid view count",
            evidence_ids=evidence_ids,
            extreme_value_rule="threshold=max(view_median*3,10000); no winsorization",
        )
    threshold = max(float(median(views)) * 3, 10000.0)
    viral_count = sum(view >= threshold for view in views)
    return _result(
        metric_name=MetricName.VIRAL_RATE,
        value=viral_count / sample_size,
        unit="ratio",
        numerator=float(viral_count),
        denominator=float(sample_size),
        sample_size=sample_size,
        time_window="representative_sample",
        missing_rule="exclude missing view; null when fewer than 3 valid samples",
        evidence_ids=evidence_ids,
        extreme_value_rule="threshold=max(view_median*3,10000); no winsorization",
    )


def relevant_content_ratio(
    *,
    relevant: int,
    irrelevant: int,
    uncertain: int,
    evidence_ids: Sequence[str],
) -> MetricResult:
    for name, value in (("relevant", relevant), ("irrelevant", irrelevant), ("uncertain", uncertain)):
        _require_nonnegative(name, value)
    denominator = relevant + irrelevant
    value = relevant / denominator if denominator > 0 else None
    return _result(
        metric_name=MetricName.RELEVANT_CONTENT_RATIO,
        value=value,
        unit="ratio",
        numerator=float(relevant),
        denominator=float(denominator),
        sample_size=relevant + irrelevant + uncertain,
        warning_sample_size=denominator,
        time_window="account_audit_window",
        missing_rule="uncertain is shown in sample_size but excluded from the denominator",
        evidence_ids=evidence_ids,
    )


def sample_coverage(*, actual_count: int, evidence_ids: Sequence[str]) -> MetricResult:
    _require_nonnegative("actual_count", actual_count)
    value = min(actual_count / REPRESENTATIVE_VIDEO_TARGET, 1.0)
    return _result(
        metric_name=MetricName.SAMPLE_COVERAGE,
        value=value,
        unit="ratio",
        numerator=float(actual_count),
        denominator=float(REPRESENTATIVE_VIDEO_TARGET),
        sample_size=actual_count,
        time_window="current_report",
        missing_rule="always calculable from the actual representative-video count",
        evidence_ids=evidence_ids,
        extreme_value_rule="cap display value at 1.0",
    )


def search_visibility(
    *,
    creator_video_count: int,
    total_deduplicated_video_count: int,
    evidence_ids: Sequence[str],
) -> MetricResult:
    _require_nonnegative("creator_video_count", creator_video_count)
    _require_nonnegative("total_deduplicated_video_count", total_deduplicated_video_count)
    if creator_video_count > total_deduplicated_video_count:
        raise ValueError("creator_video_count cannot exceed total_deduplicated_video_count")
    denominator = float(total_deduplicated_video_count)
    value = creator_video_count / total_deduplicated_video_count if total_deduplicated_video_count else None
    return _result(
        metric_name=MetricName.SEARCH_VISIBILITY,
        value=value,
        unit="ratio",
        numerator=float(creator_video_count),
        denominator=denominator,
        sample_size=total_deduplicated_video_count,
        time_window="current_search_snapshot",
        missing_rule="null when the deduplicated search pool is empty",
        evidence_ids=evidence_ids,
    )


def sample_share(
    creator_videos: Sequence[Video],
    selected_competitor_videos: Sequence[Video],
    *,
    evidence_ids: Sequence[str],
) -> MetricResult:
    creator_views = [video.view for video in creator_videos if video.view is not None]
    all_views = [video.view for video in selected_competitor_videos if video.view is not None]
    numerator = float(sum(creator_views))
    denominator = float(sum(all_views))
    if numerator > denominator:
        raise ValueError("creator sample views cannot exceed all selected-competitor sample views")
    value = numerator / denominator if denominator > 0 else None
    return _result(
        metric_name=MetricName.SAMPLE_SHARE,
        value=value,
        unit="ratio",
        numerator=numerator,
        denominator=denominator,
        sample_size=len(all_views),
        time_window="selected_competitor_sample",
        missing_rule="exclude missing view; null when valid selected-sample views sum to 0",
        evidence_ids=evidence_ids,
    )
