import json
import tempfile
import unittest
from pathlib import Path

from science_pulse.knowledge import KnowledgeBase, format_search, format_stats


class KnowledgeBaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "docs").mkdir()
        (self.root / "README.md").write_text("# SCM\n\nНаучный контент.\n", encoding="utf-8")
        (self.root / "docs" / "SCM.md").write_text("# Парадигма\n\nФормула и сигнал.\n", encoding="utf-8")
        self.kb = KnowledgeBase(self.root / "data" / "knowledge.db", root=self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_index_and_search(self):
        result = self.kb.index_documents(self.root)
        self.assertEqual(result["indexed"], 2)
        rows = self.kb.search("Научный")
        self.assertTrue(rows)
        self.assertTrue(any("README.md" in row["path"] for row in rows))
        self.assertIn("контент", format_search(rows))

    def test_reindex_skips_unchanged(self):
        self.kb.index_documents(self.root)
        result = self.kb.index_documents(self.root)
        self.assertEqual(result["indexed"], 0)
        self.assertEqual(result["skipped"], 2)

    def test_claims_and_notes_are_unproven(self):
        claim_id = self.kb.add_claim("Теорема верна", source="test")
        note_id = self.kb.add_note("Проверить формулу", source="test")
        self.assertGreater(claim_id, 0)
        self.assertGreater(note_id, 0)
        claim = self.kb.list_claims()[0]
        note = self.kb.list_notes()[0]
        self.assertEqual(claim["status"], "UNPROVEN")
        self.assertEqual(claim["owner_signed"], 0)
        self.assertEqual(note["status"], "UNPROVEN")

    def test_integrity(self):
        self.kb.index_documents(self.root)
        report = self.kb.integrity()
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["stats"]["documents"], 2)

    def test_export(self):
        self.kb.index_documents(self.root)
        self.kb.add_claim("Факт", source="test")
        path = self.kb.export_json(self.root / "export.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["stats"]["documents"], 2)
        self.assertEqual(len(data["claims"]), 1)

    def test_format_stats(self):
        text = format_stats(self.kb.stats())
        self.assertIn("SCM Knowledge Base", text)
        self.assertIn("документы", text)


if __name__ == "__main__":
    unittest.main()
