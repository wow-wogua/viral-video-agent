import tempfile
import unittest
from pathlib import Path

from src.rag.audit import build_audit


class RagAuditTests(unittest.TestCase):
    def test_audit_reports_missing_sources_and_platforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge" / "industry_methodology"
            root.mkdir(parents=True)
            (root / "method.md").write_text("# 钩子方法\n\n开头要清楚。", encoding="utf-8")

            audit = build_audit(str(Path(tmp) / "knowledge"))

            self.assertEqual(audit["document_count"], 1)
            self.assertEqual(len(audit["documents_without_source_urls"]), 1)
            self.assertIn("bilibili", audit["missing_platform_rules"])
            self.assertFalse(audit["ready"])


if __name__ == "__main__":
    unittest.main()
