import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from science_pulse.audience import AudienceCollector, AudienceDashboard
from science_pulse.config import Config
from science_pulse.growth import AudienceRegistry
from science_pulse.models import Post
from science_pulse.storage import Storage


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def fake_get(url, params=None, timeout=None):
    if "getChatMemberCount" in url:
        return FakeResponse({"ok": True, "result": 123})
    if "graph.threads.com" in url:
        return FakeResponse({"id": "1", "username": "scm", "followers_count": 456})
    raise AssertionError(url)


class AudienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={"data_dir": "data"}, root=self.root)
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.registry = AudienceRegistry(self.config.data_dir / "growth.db")
        self.env = patch.dict(
            "os.environ",
            {"TG_BOT_TOKEN": "t", "TG_CHANNEL_ID": "@c", "TH_USER_ID": "1", "TH_ACCESS_TOKEN": "t"},
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_collect_saves_snapshots(self):
        collector = AudienceCollector(self.config, self.storage, self.registry, http_get=fake_get)
        snapshots = collector.collect()
        values = {item.platform: item.followers for item in snapshots}
        self.assertEqual(values, {"telegram": 123, "threads": 456})
        latest = {item["platform"]: item["followers"] for item in self.registry.latest_snapshots()}
        self.assertEqual(latest, {"telegram": 123, "threads": 456})

    def test_missing_keys_skipped(self):
        with patch.dict("os.environ", {"TG_BOT_TOKEN": "", "TG_CHANNEL_ID": "", "TH_USER_ID": "", "TH_ACCESS_TOKEN": ""}, clear=False):
            collector = AudienceCollector(self.config, self.storage, self.registry, http_get=fake_get)
            snapshots = collector.collect()
        self.assertTrue(all(item.status == "skipped" for item in snapshots))

    def test_dashboard(self):
        self.storage.add_post(Post(id="p1", domain="math", title="Тест", body="Текст " * 30, formula_plain="x^2"))
        self.storage.mark_published("p1")
        self.storage.add_metrics("p1", "telegram", views=100, likes=5, replies=2)
        self.registry.add_snapshot("telegram", followers=123)
        self.registry.add_snapshot("threads", followers=456)
        dashboard = AudienceDashboard(self.config, self.storage, self.registry)
        report = dashboard.build()
        self.assertEqual(report["audience"]["telegram"], 123)
        self.assertEqual(report["audience"]["threads"], 456)
        self.assertEqual(report["posts"]["published"], 1)
        paths = dashboard.write()
        self.assertTrue(Path(paths["markdown"]).is_file())
        self.assertIn("Telegram: 123", Path(paths["markdown"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
