import unittest

from src.graph.v2 import stable_evidence_id
from src.reporting.validation import finalize_report, validate_claims, validate_report_references


class ReportingValidationTests(unittest.TestCase):
    def setUp(self):
        self.evidence = [{"evidence_id": "ev_12345678", "source_type": "bilibili_video", "title": "真实视频", "source_url": "https://www.bilibili.com/video/BV1"}]

    def test_stable_evidence_id_uses_source_identity(self):
        item = {"bvid": "BV1", "title": "first"}
        self.assertEqual(stable_evidence_id("search_videos", item), stable_evidence_id("search_videos", {"bvid": "BV1", "title": "changed"}))

    def test_unknown_claim_reference_fails(self):
        valid, _ = validate_claims([{"claim": "x", "claim_type": "observation", "evidence_ids": ["ev_deadbeef"]}], self.evidence)
        self.assertFalse(valid)

    def test_observation_requires_evidence(self):
        valid, _ = validate_claims([{"claim": "x", "claim_type": "observation", "evidence_ids": []}], self.evidence)
        self.assertFalse(valid)

    def test_evidence_requires_at_least_one_structured_claim(self):
        valid, reason = validate_claims([], self.evidence)
        self.assertFalse(valid)
        self.assertIn("no structured claims", reason)

    def test_deterministic_appendix_contains_claim_and_source(self):
        content = finalize_report("# 报告", [{"claim": "样本观察", "claim_type": "observation", "evidence_ids": ["ev_12345678"]}], self.evidence)
        self.assertIn("[ev_12345678]", content)
        self.assertIn("https://www.bilibili.com/video/BV1", content)
        self.assertTrue(validate_report_references(content, self.evidence)[0])

    def test_unknown_report_reference_fails(self):
        self.assertFalse(validate_report_references("错误引用 ev_deadbeef", self.evidence)[0])


if __name__ == "__main__":
    unittest.main()
