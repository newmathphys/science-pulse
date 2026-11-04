import tempfile
import unittest
from pathlib import Path

from science_pulse.admin import TelegramAdmin
from science_pulse.config import Config
from science_pulse.metrics import MetricsCollector, parse_compact_number, parse_tg_views
from science_pulse.models import Post, PublishResult
from science_pulse.pipeline import Pipeline
from science_pulse.storage import Storage


class FakeResponse:
    def __init__(self, text):
        self.text = text


class CompactNumberTests(unittest.TestCase):
    def test_suffixes(self):
        self.assertEqual(parse_compact_number("1.2K"), 1200)
        self.assertEqual(parse_compact_number("3.5M"), 3500000)
        self.assertEqual(parse_compact_number("1 234"), 1234)
        self.assertEqual(parse_compact_number("42"), 42)
        self.assertEqual(parse_compact_number("—"), 0)

    def test_views_from_widget(self):
        html = '<span class="tgme_widget_message_views">12.5K</span>'
        self.assertEqual(parse_tg_views(html), 12500)
        self.assertEqual(parse_tg_views("<div>нет данных</div>"), 0)


class TelegramMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={"telegram": {"channel_id": "@newmathphys"}}, root=self.root)
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        post = Post(id="tg1", domain="math", title="Тест метрик", body="Тело поста", formula_plain="x")
        self.storage.add_post(post)
        self.storage.record_publication(post.id, PublishResult(platform="telegram", ok=True, external_id="24"))

    def tearDown(self):
        self.temp.cleanup()

    def test_collect_reads_views(self):
        def fake_get(url, timeout=10):
            self.assertIn("t.me/newmathphys/24", url)
            return FakeResponse('<span class="tgme_widget_message_views">1.2K</span>')

        summary = MetricsCollector(self.config, self.storage, http_get=fake_get).collect(platforms=["telegram"])
        self.assertEqual(summary["stored"], 1)
        self.assertEqual(summary["samples"][0]["views"], 1200)

    def test_network_error_is_soft(self):
        def broken(url, timeout=10):
            raise TimeoutError("нет сети")

        summary = MetricsCollector(self.config, self.storage, http_get=broken).collect(platforms=["telegram"])
        self.assertEqual(summary["samples"][0]["views"], 0)


class ReactionCountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={"telegram": {"admin_chat_id": "1"}}, root=self.root)
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        post = Post(id="tg2", domain="math", title="Тест реакций", body="Тело поста", formula_plain="x")
        self.storage.add_post(post)
        self.storage.record_publication(post.id, PublishResult(platform="telegram", ok=True, external_id="24"))
        self.bot = TelegramAdmin(self.config, Pipeline(self.config), token="t", chat_id="1")

    def tearDown(self):
        self.temp.cleanup()

    def test_reaction_count_updates_likes(self):
        self.bot.handle_update({
            "message_reaction_count": {
                "message_id": 24,
                "reactions": [{"total_count": 7}, {"total_count": 5}],
            }
        })
        rows = [item for item in self.storage.metrics_summary()["by_platform"] if item["platform"] == "telegram"]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["likes"], 12)

    def test_stats_table_has_channels(self):
        self.bot.handle_update({"message_reaction_count": {"message_id": 24, "reactions": [{"total_count": 3}]}})
        text = self.bot._stats_text()
        self.assertIn("views", text)
        self.assertIn("telegram", text)


if __name__ == "__main__":
    unittest.main()
