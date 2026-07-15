import unittest
from datetime import datetime, timezone

from src.intelligence.contracts import MetricName, Video
from src.intelligence.metrics import (
    coin_rate,
    favorite_rate,
    interaction_median,
    interaction_rate,
    posting_frequency,
    relevant_content_ratio,
    reply_rate,
    sample_coverage,
    sample_share,
    search_visibility,
    view_median,
    viral_rate,
)


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)
EVIDENCE = ["ev-metric-test"]


def video(
    index: int,
    *,
    view: int | None,
    like: int | None = 0,
    coin: int | None = 0,
    favorite: int | None = 0,
    reply: int | None = 0,
    share: int | None = 0,
) -> Video:
    return Video(
        bvid=f"BV{index:010d}",
        creator_mid="creator-1",
        creator_name="脱敏账号",
        title=f"脱敏视频 {index}",
        source_url=f"https://video.example.test/{index}",
        view=view,
        like=like,
        coin=coin,
        favorite=favorite,
        reply=reply,
        share=share,
        observed_at=NOW,
        provider_name="fixture",
        provider_version="1",
        source_page=1,
        source_rank=index,
    )


class IntelligenceMetricTests(unittest.TestCase):
    def test_single_video_rates_match_hand_calculation(self):
        sample = video(1, view=100, like=10, coin=5, favorite=4, reply=3, share=2)

        interaction = interaction_rate(sample, evidence_ids=EVIDENCE)
        self.assertEqual(interaction.metric_name, MetricName.INTERACTION_RATE)
        self.assertAlmostEqual(interaction.value, 0.24)
        self.assertEqual(interaction.numerator, 24)
        self.assertEqual(interaction.denominator, 100)
        self.assertAlmostEqual(favorite_rate(sample, evidence_ids=EVIDENCE).value, 0.04)
        self.assertAlmostEqual(coin_rate(sample, evidence_ids=EVIDENCE).value, 0.05)
        self.assertAlmostEqual(reply_rate(sample, evidence_ids=EVIDENCE).value, 0.03)

    def test_single_video_rate_preserves_missing_values(self):
        sample = video(2, view=100, favorite=None)

        result = interaction_rate(sample, evidence_ids=EVIDENCE)

        self.assertIsNone(result.value)
        self.assertIsNone(result.numerator)
        self.assertEqual(result.denominator, 100)

    def test_posting_frequency_uses_fixed_thirty_day_denominator(self):
        result = posting_frequency(
            relevant_upload_count_30d=6,
            observed_upload_count_30d=10,
            recent_sample_available=True,
            evidence_ids=EVIDENCE,
        )

        self.assertAlmostEqual(result.value, 1.4)
        self.assertEqual(result.sample_size, 10)
        self.assertEqual(result.time_window, "30d")

    def test_medians_exclude_only_samples_required_by_each_formula(self):
        samples = [
            video(3, view=0, like=1, coin=1, favorite=1, reply=1, share=1),
            video(4, view=100, like=2, coin=2, favorite=2, reply=2, share=2),
            video(5, view=200, favorite=None),
            video(6, view=None, like=4, coin=4, favorite=4, reply=4, share=4),
        ]

        views = view_median(samples, evidence_ids=EVIDENCE)
        interactions = interaction_median(samples, evidence_ids=EVIDENCE)

        self.assertEqual(views.value, 100)
        self.assertEqual(views.sample_size, 3)
        self.assertEqual(interactions.value, 10)
        self.assertEqual(interactions.sample_size, 3)

    def test_viral_rate_uses_median_times_three_or_ten_thousand(self):
        samples = [video(7, view=1000), video(8, view=10000), video(9, view=40000)]

        result = viral_rate(samples, evidence_ids=EVIDENCE)

        self.assertAlmostEqual(result.value, 1 / 3)
        self.assertEqual(result.numerator, 1)
        self.assertEqual(result.denominator, 3)

    def test_viral_rate_is_null_below_three_valid_samples(self):
        result = viral_rate([video(10, view=20000), video(11, view=None)], evidence_ids=EVIDENCE)

        self.assertIsNone(result.value)
        self.assertEqual(result.sample_size, 1)
        self.assertIsNotNone(result.small_sample_warning)

    def test_relevant_ratio_excludes_uncertain_from_denominator(self):
        result = relevant_content_ratio(
            relevant=3,
            irrelevant=7,
            uncertain=2,
            evidence_ids=EVIDENCE,
        )

        self.assertAlmostEqual(result.value, 0.3)
        self.assertEqual(result.denominator, 10)
        self.assertEqual(result.sample_size, 12)

    def test_coverage_visibility_and_sample_share_are_bounded_and_named(self):
        coverage = sample_coverage(actual_count=9, evidence_ids=EVIDENCE)
        visibility = search_visibility(
            creator_video_count=2,
            total_deduplicated_video_count=8,
            evidence_ids=EVIDENCE,
        )
        creator_samples = [video(12, view=100), video(13, view=200)]
        all_samples = [*creator_samples, video(14, view=300)]
        share = sample_share(creator_samples, all_samples, evidence_ids=EVIDENCE)

        self.assertEqual(coverage.value, 1.0)
        self.assertEqual(visibility.value, 0.25)
        self.assertEqual(share.metric_name, MetricName.SAMPLE_SHARE)
        self.assertEqual(share.value, 0.5)

    def test_metric_results_require_evidence(self):
        with self.assertRaisesRegex(ValueError, "Evidence ID"):
            view_median([video(15, view=100)], evidence_ids=[])


if __name__ == "__main__":
    unittest.main()
