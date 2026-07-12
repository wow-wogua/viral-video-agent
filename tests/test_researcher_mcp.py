import unittest
from types import SimpleNamespace

from src.agents.researcher import _unwrap_mcp_result


class McpResultTests(unittest.TestCase):
    def test_fastmcp_result_wrapper_is_removed(self):
        payload = [{"title": "demo", "url": "https://example.com"}]
        result = SimpleNamespace(structured_content={"result": payload})
        self.assertEqual(_unwrap_mcp_result(result), payload)

    def test_other_structured_content_is_preserved(self):
        payload = {"status": "unavailable", "source": "unavailable"}
        result = SimpleNamespace(structured_content=payload)
        self.assertEqual(_unwrap_mcp_result(result), payload)


if __name__ == "__main__":
    unittest.main()
