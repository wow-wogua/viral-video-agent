import unittest

from src.tools.capabilities import (
    ToolUnavailableError,
    get_available_tool_names,
    get_tool_capabilities,
    normalize_tool_params,
    render_available_tools,
)


class ToolCapabilityTests(unittest.TestCase):
    def test_bilibili_search_is_available_and_normalized(self):
        params = normalize_tool_params(
            "search_videos",
            {"keyword": "科技", "platforms": ["B站"], "limit": 5},
        )
        self.assertEqual(params["platforms"], ["bilibili"])
        self.assertEqual(params["limit"], 5)

    def test_search_limit_is_capped_for_analysis_context(self):
        params = normalize_tool_params(
            "search_videos",
            {"keyword": "科技", "platforms": ["bilibili"], "limit": 50},
        )
        self.assertEqual(params["limit"], 20)

    def test_unsupported_search_platform_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_tool_params(
                "search_videos",
                {"keyword": "科技", "platforms": ["douyin"]},
            )

    def test_unavailable_tools_are_not_rendered(self):
        prompt = render_available_tools()
        capabilities = get_tool_capabilities()
        for name, capability in capabilities.items():
            if capability.enabled:
                self.assertIn(name, prompt)
            else:
                self.assertNotIn(f"- {name}(", prompt)

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(ToolUnavailableError):
            normalize_tool_params("unknown", {})

    def test_rag_platform_is_normalized(self):
        params = normalize_tool_params(
            "rag_search",
            {"query": "平台规则", "platform": "xiaohongshu"},
        )
        self.assertEqual(params["platform"], "xiaohongshu")

    def test_available_names_match_snapshot(self):
        expected = {
            name
            for name, capability in get_tool_capabilities().items()
            if capability.enabled
        }
        self.assertEqual(get_available_tool_names(), expected)


if __name__ == "__main__":
    unittest.main()
