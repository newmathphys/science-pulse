import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.recovery import parse_public_feed, recover_from_public_channel
from science_pulse.storage import Storage
from science_pulse.text import braille_sparkline


class BrailleTests(unittest.TestCase):
    def test_levels_and_unicode_range(self):
        spark = braille_sparkline([0, 1, 2, 3, 4])
        self.assertEqual(len(spark), 5)
        for char in spark:
            self.assertGreaterEqual(ord(char), 0x2800)
            self.assertLessEqual(ord(char), 0x28FF)
        self.assertEqual(ord(spark[0]), 0x2800)          # минимум — пустой
        self.assertEqual(ord(spark[-1]), 0x2800 + 0x47)  # максимум — полный столбик

    def test_downsampling_and_empty(self):
        self.assertEqual(braille_sparkline([], 8), "")
        self.assertEqual(len(braille_sparkline(list(range(100)), 16)), 16)
        self.assertEqual(len(braille_sparkline([1, 2, 3], 16)), 3)


class FeedParseTests(unittest.TestCase):
    HTML = (
        '<div class="tgme_widget_message" data-post="newmathphys/24">'
        '<div class="tgme_widget_message_text">§ 1.1 Теорема Пифагора</div></div>'
        '<div class="tgme_widget_message" data-post="newmathphys/26">'
        '<div class="tgme_widget_message_text">§ 1.2 Алгоритм Евклида</div></div>'
    )

    def test_parse(self):
        items = parse_public_feed(self.HTML)
        self.assertEqual(items, [
            {"message_id": "24", "section": "1.1"},
            {"message_id": "26", "section": "1.2"},
        ])

    def test_parse_empty(self):
        self.assertEqual(parse_public_feed(""), [])


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={"telegram": {"channel_id": "@newmathphys"}}, root=self.root)
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        from science_pulse.models import make_id
        from science_pulse.sources.history_canon import CANON

        for item in CANON[:3]:
            post = Post(id=make_id("history_canon", item["id"]), domain=item["domain"],
                        title=item["title"], body=item["body"], formula_plain=item["formula_plain"])
            post.meta["foundation_id"] = item["id"]
            self.storage.add_post(post)

    def tearDown(self):
        self.temp.cleanup()

    def test_recover_marks_published(self):
        def fake_get(url, timeout=15):
            self.assertIn("t.me/s/newmathphys", url)
            return type("R", (), {"text": FeedParseTests.HTML})()

        report = recover_from_public_channel(self.storage, self.config, http_get=fake_get)
        self.assertTrue(report["ok"])
        self.assertEqual(report["recovered"], 2)
        published = self.storage.list_posts(status="published")
        self.assertEqual(len(published), 2)

    def test_network_error_is_soft(self):
        def broken(url, timeout=15):
            raise TimeoutError("нет сети")

        report = recover_from_public_channel(self.storage, self.config, http_get=broken)
        self.assertFalse(report["ok"])
        self.assertEqual(report["recovered"], 0)

    def test_requires_username(self):
        config = Config(raw={}, root=self.root)
        report = recover_from_public_channel(self.storage, config, http_get=lambda *a, **k: None)
        self.assertFalse(report["ok"])


if __name__ == "__main__":
    unittest.main()
