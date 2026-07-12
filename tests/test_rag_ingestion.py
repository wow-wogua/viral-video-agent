import tempfile
import unittest
from pathlib import Path

from src.rag.init_db import _chroma_metadata
from src.rag.loader import load_documents
from src.rag.splitter import split_documents


class RagIngestionTests(unittest.TestCase):
    def test_loader_extracts_provenance_and_deduplicates_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge" / "platform_rules"
            root.mkdir(parents=True)
            content = """---
platform: bilibili
published_at: 2025-01-02
collected_at: 2026-07-12
source_urls:
  - https://example.com/official
source_tier: official
---
# B站规则

正文。
"""
            (root / "a.md").write_text(content, encoding="utf-8")
            (root / "duplicate.md").write_text(content, encoding="utf-8")

            docs = load_documents(str(Path(tmp) / "knowledge"))

            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0]["platform"], "bilibili")
            self.assertEqual(docs[0]["content_type"], "platform_policy")
            self.assertEqual(docs[0]["source_urls"], ["https://example.com/official"])
            self.assertEqual(docs[0]["source_count"], 1)
            self.assertEqual(docs[0]["source_tier"], "official")

    def test_platform_detection_uses_filename_not_incidental_body_mentions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge" / "platform_rules"
            root.mkdir(parents=True)
            (root / "快手规则.md").write_text(
                "# 快手规则\n\n正文顺带比较抖音和B站。",
                encoding="utf-8",
            )

            docs = load_documents(str(Path(tmp) / "knowledge"))

            self.assertEqual(docs[0]["platform"], "kuaishou")

    def test_splitter_keeps_heading_path_and_stable_ids(self):
        doc = {
            "content": "# 标题\n\n引言。\n\n## 第一节\n\n第一段。\n\n第二段。",
            "doc_id": "doc-1",
            "title": "标题",
            "source": "knowledge/a.md",
            "category": "industry_methodology",
            "platform": "generic",
            "content_type": "methodology",
            "published_at": "unknown",
            "collected_at": "2026-07-12",
            "source_urls": [],
            "source_count": 0,
            "source_tier": "internal",
            "provenance_status": "missing",
            "content_hash": "hash",
        }

        first = split_documents([doc], chunk_size=140, chunk_overlap=20)
        second = split_documents([doc], chunk_size=140, chunk_overlap=20)

        self.assertEqual([item["chunk_id"] for item in first], [item["chunk_id"] for item in second])
        self.assertTrue(any(item["heading_path"] == "标题 > 第一节" for item in first))
        self.assertTrue(all(item["content"].startswith("文档：标题") for item in first))

    def test_chroma_metadata_contains_traceability_fields(self):
        chunk = split_documents([{
            "content": "# 标题\n\n正文。",
            "doc_id": "doc-1",
            "title": "标题",
            "source": "knowledge/a.md",
            "category": "trend_data",
            "platform": "generic",
            "content_type": "trend_summary",
            "published_at": "2025",
            "collected_at": "2026-07-12",
            "source_urls": ["https://example.com"],
            "source_count": 1,
            "source_tier": "official",
            "provenance_status": "sourced",
            "content_hash": "hash",
        }], chunk_size=200, chunk_overlap=20)[0]

        metadata = _chroma_metadata(chunk)

        self.assertEqual(metadata["source_url"], "https://example.com")
        self.assertEqual(metadata["source_urls_json"], '["https://example.com"]')
        self.assertEqual(metadata["category"], "trend_data")
        self.assertIn("heading_path", metadata)
        self.assertIn("chunk_hash", metadata)


if __name__ == "__main__":
    unittest.main()
