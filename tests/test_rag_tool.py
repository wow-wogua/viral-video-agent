import asyncio
import unittest
from unittest.mock import patch

from src.tools.rag_retrieval import rag_search


class RagToolTests(unittest.TestCase):
    def test_rag_search_returns_traceable_structured_results(self):
        retrieved = [{
            "content": "正文",
            "title": "标题",
            "source": "knowledge/a.md",
            "source_url": "https://example.com/source",
            "source_urls": ["https://example.com/source", "https://example.com/second"],
            "category": "platform_rules",
            "platform": "bilibili",
            "heading_path": "标题 > 章节",
            "source_tier": "official",
        }]
        with patch("src.tools.rag_retrieval.retrieve_with_metadata", return_value=retrieved) as mock_retrieve:
            result = asyncio.run(rag_search("B站规则", top_k=3, platform="bilibili"))

        mock_retrieve.assert_called_once_with("B站规则", 3, platform="bilibili")
        self.assertEqual(result[0]["source_url"], "https://example.com/source")
        self.assertEqual(len(result[0]["source_urls"]), 2)
        self.assertEqual(result[0]["heading_path"], "标题 > 章节")
        self.assertEqual(result[0]["source_tier"], "official")


if __name__ == "__main__":
    unittest.main()
