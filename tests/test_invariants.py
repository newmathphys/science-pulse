import tempfile
import unittest
from pathlib import Path

from science_pulse.invariants import SIMHASH_RE, InvariantChecker
from science_pulse.models import Post, PublishResult
from science_pulse.storage import Storage


def make_post(pid="p1"):
    return Post(
        id=pid,
        domain="math",
        title="Тестовая теорема",
        hook="Крючок",
        body="Длинный текст с формулой $x^2$ для проверки инвариантов состояния.",
        formula_plain="x^2",
        source_name="test",
    )


class InvariantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temp.name) / "inv.db")
        self.checker = InvariantChecker(self.storage)

    def tearDown(self):
        self.temp.cleanup()

    def test_empty_state_ok(self):
        report = self.checker.check()
        self.assertTrue(report.ok)
        self.assertEqual(report.checked, 7)

    def test_clean_published_state_ok(self):
        post = make_post()
        self.storage.add_post(post)
        self.storage.mark_published(post.id, card_file_id="FILE1")
        self.storage.record_publication(post.id, PublishResult(platform="telegram", ok=True, external_id="1"))
        self.assertTrue(self.checker.check().ok)

    def test_inv2_published_without_publication(self):
        post = make_post()
        self.storage.add_post(post)
        self.storage.mark_published(post.id)
        report = self.checker.check()
        self.assertFalse(report.ok)
        self.assertIn("INV-2", {item.code for item in report.violations})

    def test_inv3_orphan_file_id(self):
        post = make_post()
        self.storage.add_post(post)
        self.storage.set_card_file_id(post.id, "ORPHAN")
        report = self.checker.check()
        self.assertIn("INV-3", {item.code for item in report.violations})

    def test_telegram_text_fallback_not_violation(self):
        # Telegram может опубликовать текст без фото (fallback) — это не нарушение.
        post = make_post()
        self.storage.add_post(post)
        self.storage.mark_published(post.id)
        self.storage.record_publication(post.id, PublishResult(platform="telegram", ok=True, external_id="24"))
        self.assertTrue(self.checker.check().ok)

    def test_inv4_unknown_status(self):
        post = make_post()
        self.storage.add_post(post)
        with self.storage.cursor() as connection:
            connection.execute("UPDATE posts SET status = 'weird' WHERE id = ?", (post.id,))
        report = self.checker.check()
        self.assertIn("INV-4", {item.code for item in report.violations})

    def test_inv5_bad_simhash(self):
        post = make_post()
        self.storage.add_post(post)
        with self.storage.cursor() as connection:
            connection.execute("UPDATE seen SET simhash = 'not-hex' WHERE post_id = ?", (post.id,))
        report = self.checker.check()
        self.assertIn("INV-5", {item.code for item in report.violations})

    def test_simhash_regex(self):
        self.assertTrue(SIMHASH_RE.match("0xffffffffffffffff"))
        self.assertTrue(SIMHASH_RE.match("12345"))
        self.assertFalse(SIMHASH_RE.match("xyz"))


if __name__ == "__main__":
    unittest.main()
