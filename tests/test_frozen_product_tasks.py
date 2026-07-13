import json
from pathlib import Path
import unittest

from src.api.schemas import JobCreate
from src.graph.v2 import requested_platforms, requires_analysis_workflow


class FrozenProductTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "src" / "eval" / "cases" / "bilibili_mvp_frozen20.json"
        cls.cases = json.loads(path.read_text(encoding="utf-8"))

    def test_exactly_twenty_frozen_tasks(self):
        self.assertEqual(len(self.cases), 20)
        self.assertEqual(len({case["id"] for case in self.cases}), 20)

    def test_all_tasks_pass_product_input_and_bilibili_boundary(self):
        for case in self.cases:
            payload = JobCreate(query=case["query"], platforms=["bilibili"], analysis_mode=case["analysis_mode"], idempotency_key=f"frozen-{case['id']}")
            self.assertEqual(payload.platforms, ["bilibili"])
            self.assertTrue(requires_analysis_workflow(payload.query), case["id"])
            self.assertEqual(requested_platforms(payload.query, payload.platforms), {"bilibili"})


if __name__ == "__main__":
    unittest.main()
