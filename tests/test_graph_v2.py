import asyncio
import unittest

from src.api.status import result_status
from src.graph.builder import build_graph
from src.graph.v2 import (
    evidence_gate_node,
    dedupe_new_data,
    entry_node,
    requested_platforms,
    requires_analysis_workflow,
    requires_current_video_data,
    route_analyst,
    route_entry,
    route_evidence,
    route_research,
    route_writer,
)


class GraphV2Tests(unittest.TestCase):
    def test_v1_and_v2_graphs_compile(self):
        self.assertIsNotNone(build_graph("v1"))
        self.assertIsNotNone(build_graph("v2"))

    def test_evidence_gate_accepts_real_evidence(self):
        result = evidence_gate_node({
            "evidence": [{"evidence_id": "ev_1"}],
            "tool_results": [{"status": "success"}],
        })
        self.assertTrue(result["data_sufficient"])
        self.assertNotIn("termination_reason", result)

    def test_evidence_gate_stops_without_evidence(self):
        result = evidence_gate_node({
            "evidence": [],
            "tool_results": [{"status": "empty"}],
        })
        self.assertFalse(result["data_sufficient"])
        self.assertTrue(result["task_complete"])
        self.assertEqual(result["termination_reason"], "insufficient_evidence")
        self.assertTrue(result["report_final"])

    def test_unavailable_tool_maps_to_partial_status(self):
        result = evidence_gate_node({
            "evidence": [],
            "tool_results": [{"status": "unavailable"}],
        })
        self.assertEqual(result["termination_reason"], "tool_unavailable")
        self.assertEqual(result_status(result), ("partial", "tool_unavailable"))

    def test_routes_are_deterministic(self):
        self.assertEqual(route_entry({"task_complete": True}), "end")
        self.assertEqual(route_entry({"task_complete": False}), "planner_v2")
        self.assertEqual(
            route_research({"current_step": 1, "research_tasks": [{}, {}]}),
            "researcher_v2",
        )
        self.assertEqual(
            route_research({"current_step": 2, "research_tasks": [{}, {}]}),
            "evidence_gate",
        )
        self.assertEqual(route_evidence({"data_sufficient": False}), "end")
        self.assertEqual(route_evidence({"data_sufficient": True}), "analyst")
        self.assertEqual(route_analyst({"analysis_confidence": 0.9, "analysis_iterations": 1}), "writer")
        self.assertEqual(route_writer({"report_final": "done"}), "end")

    def test_analysis_intent_is_deterministic(self):
        self.assertTrue(requires_analysis_workflow("分析B站科技区最近的爆款视频"))
        self.assertTrue(requires_analysis_workflow("搜索抖音热门视频样本"))
        self.assertFalse(requires_analysis_workflow("你好"))
        self.assertFalse(requires_analysis_workflow(""))

    def test_current_data_and_platform_detection(self):
        self.assertTrue(requires_current_video_data("搜索抖音最近的热门视频样本"))
        self.assertFalse(requires_current_video_data("查一下抖音算法规则"))
        self.assertEqual(
            requested_platforms("搜索抖音热门视频", ["bilibili"]),
            {"bilibili", "douyin"},
        )

    def test_unsupported_current_platform_stops_before_planning(self):
        result = asyncio.run(entry_node({
            "user_request": "搜索抖音最近的热门视频样本",
            "platforms": ["douyin"],
        }))
        self.assertTrue(result["task_complete"])
        self.assertEqual(result["termination_reason"], "unsupported_platform")
        self.assertTrue(result["report_final"])

    def test_research_data_is_deduplicated_by_video_identity(self):
        existing = [{"bvid": "BV1", "title": "old"}]
        fetched = [
            {"bvid": "BV1", "title": "duplicate"},
            {"bvid": "BV2", "title": "new"},
        ]
        self.assertEqual(dedupe_new_data(fetched, existing), [fetched[1]])


if __name__ == "__main__":
    unittest.main()
