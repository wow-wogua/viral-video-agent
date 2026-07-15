import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from src.intelligence.contracts import (
    CREATOR_QUALIFICATION_POLICY_VERSION,
    CrawlRun,
    CrawlStatus,
    CoverageSummary,
    CreatorQualificationEvidence,
    CreatorQualificationStatus,
    IntelligenceReport,
    PageStatus,
    ProviderCapabilities,
    SearchPage,
    SearchRequest,
)
from src.intelligence.evaluation import (
    CreatorQualificationPolicy,
    CreatorReviewDecision,
    CreatorRole,
    DiscoverySource,
    EvaluationKeyword,
    ExpectedRelevantCreator,
    FocusLevel,
    KeywordCategory,
    ReviewStatus,
    TopCreatorLabel,
    validate_evaluation_file,
)


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


def provider() -> ProviderCapabilities:
    return ProviderCapabilities(
        provider_name="fixture",
        provider_version="1",
        provider_kind="fixture",
        supports_search=True,
        supports_creator_samples=False,
        supports_native_sort=["relevance"],
        supports_native_time_range=["all"],
        commercial_authorization="development_only",
    )


def request(max_pages: int = 5) -> SearchRequest:
    return SearchRequest(keyword="脱敏关键词", max_pages=max_pages, idempotency_key="contract-test")


def page(number: int, status: PageStatus = PageStatus.SUCCESS, count: int = 1) -> SearchPage:
    return SearchPage(
        page_number=number,
        status=status,
        requested_at=NOW,
        completed_at=NOW,
        request_duration_ms=10,
        raw_result_count=count,
        normalized_result_count=count,
        provider_name="fixture",
        provider_version="1",
    )


def qualification_evidence(
    *,
    relevant: int,
    irrelevant: int,
    uncertain: int = 0,
    recent_relevant: int | None = None,
    follower_count: int | None = None,
    relevant_view_median: float | None = None,
) -> CreatorQualificationEvidence:
    audited_count = relevant + irrelevant + uncertain
    recent_relevant = relevant if recent_relevant is None else recent_relevant
    return CreatorQualificationEvidence(
        profile_url="https://space.example.test/creator",
        observed_at=NOW,
        audited_upload_count=audited_count,
        recent_90d_upload_count=audited_count,
        relevant_video_count=relevant,
        irrelevant_video_count=irrelevant,
        uncertain_video_count=uncertain,
        recent_90d_relevant_video_count=recent_relevant,
        follower_count=follower_count,
        relevant_view_median=relevant_view_median,
        evidence_urls=[f"https://video.example.test/{index}" for index in range(relevant)],
    )


def reference_creator(
    *,
    mid: str,
    name: str,
    status: CreatorQualificationStatus,
    evidence: CreatorQualificationEvidence | None,
    in_retrieved_pool: bool,
    role: CreatorRole = CreatorRole.GENERALIST,
) -> ExpectedRelevantCreator:
    return ExpectedRelevantCreator(
        mid=mid,
        name=name,
        role=role,
        focus_level=FocusLevel.MEDIUM,
        discovery_source=DiscoverySource.TARGETED_MANUAL_SEARCH,
        in_retrieved_pool=in_retrieved_pool,
        reason="脱敏账号资格测试。",
        qualification_status=status,
        review_decision=(
            CreatorReviewDecision.KEEP
            if status in {
                CreatorQualificationStatus.EMERGING_CANDIDATE,
                CreatorQualificationStatus.QUALIFIED_REFERENCE,
            }
            else CreatorReviewDecision.UNREVIEWED
        ),
        qualification_policy_version=(
            CREATOR_QUALIFICATION_POLICY_VERSION
            if status in {
                CreatorQualificationStatus.EMERGING_CANDIDATE,
                CreatorQualificationStatus.QUALIFIED_REFERENCE,
            }
            else None
        ),
        qualification_evidence=evidence,
    )


class IntelligenceContractTests(unittest.TestCase):
    def test_search_request_never_exceeds_five_pages(self):
        with self.assertRaises(ValidationError):
            request(max_pages=6)

    def test_search_request_serialization_round_trip_preserves_version_and_enums(self):
        original = request(max_pages=3)

        restored = SearchRequest.model_validate_json(original.model_dump_json())

        self.assertEqual(restored, original)
        self.assertEqual(restored.schema_version, "content-intelligence.p0.1")
        self.assertEqual(restored.sort_mode.value, "relevance")

    def test_search_request_rejects_unknown_enum_values(self):
        payload = request().model_dump(mode="json")
        payload["sort_mode"] = "benchmark_specific_sort"

        with self.assertRaises(ValidationError):
            SearchRequest.model_validate(payload)

    def test_zero_successful_pages_is_not_normal_success(self):
        with self.assertRaises(ValidationError):
            CrawlRun(
                crawl_run_id="run-1",
                request=request(1),
                provider=provider(),
                started_at=NOW,
                status=CrawlStatus.SUCCESS,
                pages=[page(1, PageStatus.FAILED, 0)],
                coverage=CoverageSummary(
                    requested_pages=1,
                    successful_pages=0,
                    raw_result_count=0,
                    deduplicated_video_count=0,
                    candidate_creator_count=0,
                    actual_competitor_count=0,
                    partial_success=False,
                ),
            )

    def test_page_status_matches_normalized_result_count(self):
        with self.assertRaisesRegex(ValidationError, "success pages require"):
            page(1, PageStatus.SUCCESS, 0)
        empty_page = page(1, PageStatus.EMPTY, 0)
        self.assertTrue(empty_page.completed_successfully)

    def test_all_empty_pages_have_explicit_empty_status(self):
        run = CrawlRun(
            crawl_run_id="run-empty",
            request=request(1),
            provider=provider(),
            started_at=NOW,
            status=CrawlStatus.EMPTY,
            pages=[page(1, PageStatus.EMPTY, 0)],
            coverage=CoverageSummary(
                requested_pages=1,
                successful_pages=1,
                raw_result_count=0,
                deduplicated_video_count=0,
                candidate_creator_count=0,
                actual_competitor_count=0,
                partial_success=False,
            ),
        )
        self.assertFalse(run.can_generate_normal_report)

    def test_all_requested_pages_cannot_be_marked_partial(self):
        with self.assertRaisesRegex(ValidationError, "partial_success"):
            CrawlRun(
                crawl_run_id="run-not-partial",
                request=request(1),
                provider=provider(),
                started_at=NOW,
                status=CrawlStatus.PARTIAL,
                pages=[page(1)],
                coverage=CoverageSummary(
                    requested_pages=1,
                    successful_pages=1,
                    raw_result_count=1,
                    deduplicated_video_count=1,
                    candidate_creator_count=1,
                    actual_competitor_count=1,
                    partial_success=True,
                ),
            )

    def test_crawl_pages_cannot_repeat_page_numbers(self):
        with self.assertRaisesRegex(ValidationError, "unique page numbers"):
            CrawlRun(
                crawl_run_id="run-duplicate-page",
                request=request(2),
                provider=provider(),
                started_at=NOW,
                status=CrawlStatus.SUCCESS,
                pages=[page(1), page(1)],
                coverage=CoverageSummary(
                    requested_pages=2,
                    successful_pages=2,
                    raw_result_count=2,
                    deduplicated_video_count=2,
                    candidate_creator_count=1,
                    actual_competitor_count=1,
                    partial_success=False,
                ),
            )

    def test_one_to_four_successful_pages_is_partial(self):
        run = CrawlRun(
            crawl_run_id="run-2",
            request=request(5),
            provider=provider(),
            started_at=NOW,
            status=CrawlStatus.PARTIAL,
            pages=[page(1), page(2), page(3, PageStatus.FAILED, 0)],
            coverage=CoverageSummary(
                requested_pages=5,
                successful_pages=2,
                raw_result_count=2,
                deduplicated_video_count=2,
                candidate_creator_count=1,
                actual_competitor_count=1,
                partial_success=True,
                truncation_reason="page_failure",
            ),
        )
        self.assertFalse(run.can_generate_normal_report)

    def test_partial_report_requires_visible_notice(self):
        with self.assertRaises(ValidationError):
            IntelligenceReport(
                report_id="report-1",
                crawl_run_id="run-2",
                generated_at=NOW,
                report_status="partial",
                query=request(5),
                provider=provider(),
                coverage=CoverageSummary(
                    requested_pages=5,
                    successful_pages=2,
                    raw_result_count=2,
                    deduplicated_video_count=2,
                    candidate_creator_count=1,
                    actual_competitor_count=0,
                    partial_success=True,
                ),
                competitors=[],
            )

    def test_partial_empty_result_is_insufficient_data_not_normal_partial(self):
        report = IntelligenceReport(
            report_id="report-partial-empty",
            crawl_run_id="run-partial-empty",
            generated_at=NOW,
            report_status="insufficient_data",
            query=request(2),
            provider=provider(),
            coverage=CoverageSummary(
                requested_pages=2,
                successful_pages=1,
                raw_result_count=0,
                deduplicated_video_count=0,
                candidate_creator_count=0,
                actual_competitor_count=0,
                partial_success=True,
            ),
            competitors=[],
            partial_success_notice="仅一页成功且没有可分析视频。",
        )

        self.assertEqual(report.report_status, "insufficient_data")

    def test_success_report_requires_a_serialized_competitor(self):
        with self.assertRaisesRegex(ValidationError, "at least one competitor"):
            IntelligenceReport(
                report_id="report-empty-competitors",
                crawl_run_id="run-success",
                generated_at=NOW,
                report_status="success",
                query=request(1),
                provider=provider(),
                coverage=CoverageSummary(
                    requested_pages=1,
                    successful_pages=1,
                    raw_result_count=1,
                    deduplicated_video_count=1,
                    candidate_creator_count=1,
                    actual_competitor_count=0,
                    partial_success=False,
                ),
                competitors=[],
            )

    def test_sanitized_evaluation_fixture_has_required_distribution(self):
        path = Path(__file__).parent / "fixtures" / "intelligence_eval" / "development_fixture.json"
        suite = validate_evaluation_file(path)
        self.assertEqual(len(suite.keywords), 20)
        self.assertFalse(suite.contains_hidden_holdout)

    def test_evaluation_fixture_rejects_an_unknown_schema_version(self):
        fixture_path = Path(__file__).parent / "fixtures" / "intelligence_eval" / "development_fixture.json"
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        payload["schema_version"] = "content-intelligence-eval.future"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong-version.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValidationError):
                validate_evaluation_file(path)

    def test_fixture_uses_only_sanitized_keyword_placeholders(self):
        path = Path(__file__).parent / "fixtures" / "intelligence_eval" / "development_fixture.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        allowed_prefixes = ("宽泛赛道", "垂类主题", "品牌样例", "歧义词", "稀疏主题")
        self.assertTrue(all(item["keyword"].startswith(allowed_prefixes) for item in payload["keywords"]))

    def test_creator_review_supports_uncertain_without_forcing_relevance(self):
        label = TopCreatorLabel(
            mid="123",
            name="样例账号",
            relevant=None,
            decision=CreatorReviewDecision.UNCERTAIN,
            reason="近期样本不足",
        )
        self.assertIsNone(label.relevant)

    def test_review_status_cannot_overstate_human_reviewer_count(self):
        with self.assertRaisesRegex(ValidationError, "reviewer_count=0"):
            EvaluationKeyword(
                id="bad-initial-reviewer-count",
                keyword="脱敏关键词甲",
                category=KeywordCategory.BROAD,
                rationale="初始标签不等于人工复核。",
                review_status=ReviewStatus.INITIAL_LABELED,
                reviewer_count=1,
            )
        with self.assertRaisesRegex(ValidationError, "two human reviewers"):
            EvaluationKeyword(
                id="bad-adjudicated-reviewer-count",
                keyword="脱敏关键词乙",
                category=KeywordCategory.BROAD,
                rationale="裁决状态必须有真实双人复核。",
                review_status=ReviewStatus.ADJUDICATED,
                reviewer_count=1,
            )

    def test_legacy_reference_candidate_defaults_to_discovery_only(self):
        creator = ExpectedRelevantCreator(
            mid="sanitized-mid",
            name="综合创作者样例",
            role=CreatorRole.SPECIALIST,
            focus_level=FocusLevel.HIGH,
            discovery_source=DiscoverySource.TARGETED_MANUAL_SEARCH,
            in_retrieved_pool=False,
            reason="定向搜索发现，但尚未完成账号级资格审计。",
        )
        self.assertFalse(creator.in_retrieved_pool)
        self.assertEqual(creator.qualification_status, CreatorQualificationStatus.DISCOVERY_ONLY)

    def test_legacy_keep_is_not_an_account_qualified_top5(self):
        label = TopCreatorLabel(
            mid="legacy-keep",
            name="仅搜索片段保留样例",
            relevant=True,
            decision=CreatorReviewDecision.KEEP,
            reason="只完成了搜索结果相关性判断。",
            rank=1,
        )
        keyword = EvaluationKeyword(
            id="legacy-keep-keyword",
            keyword="脱敏关键词",
            category=KeywordCategory.BROAD,
            rationale="旧keep不能替代账号级资格。",
            top_creators=[label],
            qualified_top5_count=0,
        )

        self.assertEqual(label.qualification_status, CreatorQualificationStatus.DISCOVERY_ONLY)
        self.assertEqual(keyword.qualified_top_creators, [])

    def test_qualified_top5_count_must_match_account_qualified_creators(self):
        with self.assertRaisesRegex(ValidationError, "qualified_top5_count"):
            EvaluationKeyword(
                id="bad-qualified-count",
                keyword="脱敏关键词",
                category=KeywordCategory.BROAD,
                rationale="不能把搜索片段keep数写成合格Top5数。",
                top_creators=[
                    TopCreatorLabel(
                        mid="legacy-keep",
                        name="仅搜索片段保留样例",
                        relevant=True,
                        decision=CreatorReviewDecision.KEEP,
                        reason="尚未完成账号级审计。",
                        rank=1,
                    )
                ],
                qualified_top5_count=1,
            )

    def test_account_qualified_top_creator_is_counted(self):
        label = TopCreatorLabel(
            mid="qualified-top",
            name="合格Top5样例",
            relevant=True,
            decision=CreatorReviewDecision.KEEP,
            role=CreatorRole.GENERALIST,
            focus_level=FocusLevel.MEDIUM,
            reason="账号级证据完整。",
            rank=1,
            qualification_status=CreatorQualificationStatus.QUALIFIED_REFERENCE,
            qualification_policy_version=CREATOR_QUALIFICATION_POLICY_VERSION,
            qualification_evidence=qualification_evidence(
                relevant=4,
                irrelevant=16,
                follower_count=10000,
            ),
        )
        keyword = EvaluationKeyword(
            id="qualified-top-keyword",
            keyword="脱敏关键词",
            category=KeywordCategory.BROAD,
            rationale="账号级Top5计数测试。",
            top_creators=[label],
            qualified_top5_count=1,
        )

        keyword.validate_reference_qualifications(CreatorQualificationPolicy())
        self.assertEqual([creator.mid for creator in keyword.qualified_top_creators], ["qualified-top"])

    def test_discovery_and_emerging_candidates_do_not_enter_retrieval_recall(self):
        discovery = reference_creator(
            mid="discovery",
            name="搜索发现样例",
            status=CreatorQualificationStatus.DISCOVERY_ONLY,
            evidence=None,
            in_retrieved_pool=True,
        )
        emerging = reference_creator(
            mid="emerging",
            name="新兴账号样例",
            status=CreatorQualificationStatus.EMERGING_CANDIDATE,
            evidence=qualification_evidence(
                relevant=4,
                irrelevant=6,
                follower_count=9999,
                relevant_view_median=4999,
            ),
            in_retrieved_pool=True,
        )
        qualified = reference_creator(
            mid="qualified",
            name="合格参考样例",
            status=CreatorQualificationStatus.QUALIFIED_REFERENCE,
            evidence=qualification_evidence(relevant=3, irrelevant=7, follower_count=10000),
            in_retrieved_pool=False,
        )
        keyword = EvaluationKeyword(
            id="test-recall",
            keyword="脱敏宽泛词",
            category=KeywordCategory.BROAD,
            rationale="测试Recall分母。",
            expected_relevant_creators=[discovery, emerging, qualified],
        )

        keyword.validate_reference_qualifications(CreatorQualificationPolicy())

        self.assertEqual([creator.mid for creator in keyword.qualified_reference_creators], ["qualified"])
        self.assertEqual(keyword.retrieval_recall, 0.0)

    def test_single_search_hit_cannot_be_upgraded_to_qualified_reference(self):
        creator = reference_creator(
            mid="single-hit",
            name="单条命中账号样例",
            status=CreatorQualificationStatus.QUALIFIED_REFERENCE,
            evidence=qualification_evidence(relevant=1, irrelevant=0, follower_count=500000),
            in_retrieved_pool=True,
        )
        keyword = EvaluationKeyword(
            id="test-single-hit",
            keyword="脱敏宽泛词",
            category=KeywordCategory.BROAD,
            rationale="单条搜索视频不能证明账号资格。",
            expected_relevant_creators=[creator],
        )

        with self.assertRaisesRegex(ValueError, "at least 3 relevant videos"):
            keyword.validate_reference_qualifications(CreatorQualificationPolicy())

    def test_mixed_generalist_below_twenty_percent_cannot_be_qualified(self):
        creator = reference_creator(
            mid="mixed-generalist",
            name="内容较杂账号样例",
            status=CreatorQualificationStatus.QUALIFIED_REFERENCE,
            evidence=qualification_evidence(relevant=3, irrelevant=17, follower_count=500000),
            in_retrieved_pool=False,
        )
        keyword = EvaluationKeyword(
            id="test-mixed-generalist",
            keyword="脱敏宽泛词",
            category=KeywordCategory.BROAD,
            rationale="模拟知名综合账号被少量相关视频误升级。",
            expected_relevant_creators=[creator],
        )

        with self.assertRaisesRegex(ValueError, "relevant content ratio"):
            keyword.validate_reference_qualifications(CreatorQualificationPolicy())

    def test_historical_burst_without_recent_relevance_cannot_be_qualified(self):
        creator = reference_creator(
            mid="historical-only",
            name="历史集中投稿账号样例",
            status=CreatorQualificationStatus.QUALIFIED_REFERENCE,
            evidence=qualification_evidence(
                relevant=10,
                irrelevant=1,
                recent_relevant=0,
                follower_count=500000,
                relevant_view_median=60000,
            ),
            in_retrieved_pool=False,
        )
        keyword = EvaluationKeyword(
            id="test-historical-only",
            keyword="脱敏品牌词",
            category=KeywordCategory.BRAND,
            rationale="历史上高度相关但近90天不活跃，不能代表当前竞争格局。",
            expected_relevant_creators=[creator],
        )

        with self.assertRaisesRegex(ValueError, "recent 90-day window"):
            keyword.validate_reference_qualifications(CreatorQualificationPolicy())

    def test_influence_shortfall_is_emerging_not_qualified(self):
        evidence = qualification_evidence(
            relevant=3,
            irrelevant=7,
            follower_count=9999,
            relevant_view_median=4999,
        )
        qualified = reference_creator(
            mid="impact-shortfall-qualified",
            name="影响力不足样例",
            status=CreatorQualificationStatus.QUALIFIED_REFERENCE,
            evidence=evidence,
            in_retrieved_pool=True,
            role=CreatorRole.SPECIALIST,
        )
        emerging = reference_creator(
            mid="impact-shortfall-emerging",
            name="影响力不足样例",
            status=CreatorQualificationStatus.EMERGING_CANDIDATE,
            evidence=evidence,
            in_retrieved_pool=True,
            role=CreatorRole.SPECIALIST,
        )
        qualified_keyword = EvaluationKeyword(
            id="test-impact-qualified",
            keyword="脱敏垂类词",
            category=KeywordCategory.VERTICAL,
            rationale="影响力门槛测试。",
            expected_relevant_creators=[qualified],
        )
        emerging_keyword = EvaluationKeyword(
            id="test-impact-emerging",
            keyword="脱敏垂类词",
            category=KeywordCategory.VERTICAL,
            rationale="影响力门槛测试。",
            expected_relevant_creators=[emerging],
        )

        with self.assertRaisesRegex(ValueError, "does not meet influence threshold"):
            qualified_keyword.validate_reference_qualifications(CreatorQualificationPolicy())
        emerging_keyword.validate_reference_qualifications(CreatorQualificationPolicy())
        self.assertIsNone(emerging_keyword.retrieval_recall)

    def test_require_reviewed_rejects_incomplete_qualified_reference_evidence(self):
        fixture_path = Path(__file__).parent / "fixtures" / "intelligence_eval" / "development_fixture.json"
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        for item in payload["keywords"]:
            item["review_status"] = "user_reviewed"
            item["reviewer_count"] = 1
            item["intent_definition"] = "脱敏业务意图"
            item["snapshots"] = [
                {
                    "searched_at": NOW.isoformat(),
                    "provider": "fixture",
                    "snapshot_file": "sanitized.json",
                    "successful_pages": 1,
                    "raw_result_count": 1,
                }
            ]
        payload["keywords"][0]["expected_relevant_creators"] = [
            {
                "mid": "single-hit-reviewed",
                "name": "单条命中账号样例",
                "role": "generalist",
                "focus_level": "medium",
                "discovery_source": "targeted_manual_search",
                "in_retrieved_pool": False,
                "reason": "只有单条相关视频。",
                "qualification_status": "qualified_reference",
                "review_decision": "keep",
                "qualification_policy_version": CREATOR_QUALIFICATION_POLICY_VERSION,
                "qualification_evidence": {
                    "profile_url": "https://space.example.test/single-hit",
                    "observed_at": NOW.isoformat(),
                    "audited_upload_count": 1,
                    "recent_90d_upload_count": 1,
                    "relevant_video_count": 1,
                    "irrelevant_video_count": 0,
                    "uncertain_video_count": 0,
                    "recent_90d_relevant_video_count": 1,
                    "follower_count": 500000,
                    "relevant_view_median": 500000,
                    "evidence_urls": ["https://video.example.test/only-hit"],
                },
            }
        ]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviewed.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "at least 3 relevant videos"):
                validate_evaluation_file(path, require_reviewed=True)


if __name__ == "__main__":
    unittest.main()
