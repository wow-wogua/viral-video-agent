import unittest

from src.eval.capability_routing_eval import params_match


class CapabilityScoringTests(unittest.TestCase):
    def test_keyword_equivalence(self):
        self.assertTrue(params_match({"keyword": "B站科技区"}, {"keyword": "科技"}))

    def test_query_equivalence(self):
        self.assertTrue(
            params_match(
                {"query": "查一下竞品分析方法论资料"},
                {"query": "竞品分析方法论"},
            )
        )

    def test_platform_mismatch_fails(self):
        self.assertFalse(
            params_match(
                {"platforms": ["douyin"]},
                {"platforms": ["bilibili"]},
            )
        )


if __name__ == "__main__":
    unittest.main()
