import unittest
from types import SimpleNamespace

from src.agents.researcher import MCPToolExecutionError, _unwrap_mcp_result


class McpResultTests(unittest.TestCase):
    def test_fastmcp_result_wrapper_is_removed(self):
        payload = [{"title": "demo", "url": "https://example.com"}]
        result = SimpleNamespace(structured_content={"result": payload})
        self.assertEqual(_unwrap_mcp_result(result), payload)

    def test_other_structured_content_is_preserved(self):
        payload = {"status": "unavailable", "source": "unavailable"}
        result = SimpleNamespace(structured_content=payload)
        self.assertEqual(_unwrap_mcp_result(result), payload)

    def test_tool_error_is_not_returned_as_evidence_data(self):
        result = SimpleNamespace(isError=True, content=[{"text": "provider error"}])
        with self.assertRaises(MCPToolExecutionError):
            _unwrap_mcp_result(result)


if __name__ == "__main__":
    unittest.main()
