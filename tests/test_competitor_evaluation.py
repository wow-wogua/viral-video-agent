from src.intelligence.competitor_evaluation import aggregate_evaluation, evaluate_keyword
from src.intelligence.evaluation import EvaluationKeyword


def keyword_fixture(category="vertical") -> EvaluationKeyword:
    evidence = {
        "profile_url": "https://example.test/creator",
        "observed_at": "2026-07-16T12:00:00Z",
        "audited_upload_count": 5,
        "recent_90d_upload_count": 5,
        "relevant_video_count": 4,
        "irrelevant_video_count": 1,
        "uncertain_video_count": 0,
        "recent_90d_relevant_video_count": 4,
        "follower_count": 20000,
        "relevant_view_median": 6000,
        "evidence_urls": ["https://example.test/1", "https://example.test/2", "https://example.test/3"],
    }
    return EvaluationKeyword.model_validate({
        "id": "sanitized-keyword-id",
        "keyword": "sanitized keyword",
        "category": category,
        "rationale": "fixture",
        "intent_definition": "sanitized intent",
        "review_status": "user_reviewed",
        "reviewer_count": 1,
        "qualified_top5_count": 0,
        "top_creators": [{
            "mid": "90003",
            "name": "sanitized irrelevant",
            "relevant": False,
            "decision": "exclude",
            "role": "unrelated",
            "focus_level": "low",
            "reason": "fixture excluded",
            "qualification_status": "excluded",
        }],
        "expected_relevant_creators": [
            {
                "mid": mid,
                "name": f"sanitized relevant {mid}",
                "role": "specialist",
                "focus_level": "high",
                "discovery_source": "retrieved_snapshot",
                "in_retrieved_pool": True,
                "reason": "fixture qualified",
                "qualification_status": "qualified_reference",
                "review_decision": "keep",
                "qualification_policy_version": "creator-qualification.p0.1",
                "qualification_evidence": evidence,
            }
            for mid in ("90001", "90002")
        ],
    })


def test_less_than_five_uses_retrieved_qualified_slots_and_reports_shortfall():
    metrics = evaluate_keyword(
        keyword_fixture(),
        selected_mids=["90001"],
        retrieved_mids=["90001", "90002", "90003"],
    )
    assert metrics.selected_precision == 1
    assert metrics.strict_precision_at_5 == 0.5
    assert metrics.output_coverage == 0.5
    assert metrics.shortfall_count == 1


def test_unknown_and_known_irrelevant_selections_are_not_hidden():
    metrics = evaluate_keyword(
        keyword_fixture(),
        selected_mids=["90001", "90003", "99999"],
        retrieved_mids=["90001", "90002", "90003", "99999"],
    )
    assert metrics.selected_precision == 1 / 3
    assert metrics.irrelevant_false_positive_rate == 1 / 3
    assert metrics.unresolved_selection_rate == 1 / 3


def test_retrieval_recall_and_category_aggregation_remain_separate():
    first = evaluate_keyword(
        keyword_fixture("vertical"),
        selected_mids=["90001", "90002"],
        retrieved_mids=["90001", "90002"],
    )
    second_keyword = keyword_fixture("broad").model_copy(update={"id": "broad-id"})
    second = evaluate_keyword(
        second_keyword,
        selected_mids=[],
        retrieved_mids=["90001"],
    )
    result = aggregate_evaluation([first, second])
    assert result["overall"]["retrieval_recall"] == 0.75
    assert result["overall"]["abstention_keyword_count"] == 1
    assert set(result["by_category"]) == {"broad", "vertical"}
