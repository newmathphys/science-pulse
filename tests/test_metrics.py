import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from science_pulse.config import Config
from science_pulse.metrics import MetricsCollector, format_metrics_summary
from science_pulse.models import Post, PublishResult
from science_pulse.storage import Storage


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def make_post():
    return Post(
        id="p1",
        domain="physics",
        title="Квантовый осциллятор и его спектр",
        hook="Как устроен спектр?",
        body="Достаточно длинный текст с формулой $E_n=\\hbar\\omega(n+1/2)$ для проверки метрик.",
        formula_latex="E_n=\\hbar\\omega(n+1/2)",
        formula_plain="E_n=hbar omega(n+1/2)",
        source_name="test",
        source_url="https://example.org",
    )


class FakeHTTP:
    """Маршрутизатор ответов площадок без выхода в сеть."""

    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if "api/v1/statuses" in url:
            return FakeResponse({"favourites_count": 5, "replies_count": 2})
        if "getPostThread" in url:
            return FakeResponse(
                {"thread": {"post": {"likeCount": 9, "replyCount": 3, "viewCount": 100}}}
            )
        if "wall.getById" in url:
            return FakeResponse(
                {
                    "response": {
                        "items": [
                            {"views": {"count": 77}, "likes": {"count": 4}, "comments": {"count": 1}}
                        ]
                    }
                }
            )
        if "insights" in url:
            return FakeResponse(
                {
                    "data": [
                        {"name": "views", "values": [{"value": 12}]},
                        {"name": "likes", "values": [{"value": 1}]},
                        {"name": "replies", "values": [{"value": 0}]},
                    ]
                }
            )
        raise AssertionError(f"неожиданный URL: {url}")


ENV = {
    "MASTODON_ACCESS_TOKEN": "mtoken",
    "VK_ACCESS_TOKEN": "vtoken",
    "TH_ACCESS_TOKEN": "ttoken",
    "TH_USER_ID": "99",
}


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(
            raw={"data_dir": "data", "dist_dir": "dist", "vk": {"group_id": "123"}},
            root=self.root,
        )
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.post = make_post()
        self.storage.add_post(self.post)
        self.storage.mark_published(self.post.id)
        self._publish("mastodon", "42", "https://mathstodon.xyz/@x/42")
        self._publish("bluesky", "at://did:plc:x/app.bsky.feed.post/abc", None)
        self._publish("vk", "55", "https://vk.com/wall-123_55")
        self._publish("threads", "t1", None)
        self._publish("telegram", "7", None)
        self.http = FakeHTTP()

    def tearDown(self):
        self.temp.cleanup()

    def _publish(self, platform, external_id, url):
        self.storage.record_publication(
            self.post.id,
            PublishResult(platform=platform, ok=True, external_id=external_id, url=url),
        )

    def _collect(self, **kwargs):
        with patch.dict("os.environ", ENV, clear=False):
            collector = MetricsCollector(self.config, self.storage, http_get=self.http.get)
            return collector.collect(**kwargs)

    def test_collect_supported_platforms(self):
        result = self._collect()
        self.assertEqual(result["targets"], 5)
        self.assertEqual(result["stored"], 4)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["errors"], 0)
        telegram = [item for item in result["samples"] if item["platform"] == "telegram"][0]
        self.assertEqual(telegram["status"], "skipped")

    def test_summary_totals(self):
        self._collect()
        summary = self.storage.metrics_summary()
        self.assertEqual(summary["totals"]["views"], 100 + 77 + 12)
        self.assertEqual(summary["totals"]["likes"], 5 + 9 + 4 + 1)
        self.assertEqual(summary["totals"]["replies"], 2 + 3 + 1 + 0)
        platforms = {item["platform"] for item in summary["by_platform"]}
        self.assertEqual(platforms, {"mastodon", "bluesky", "vk", "threads"})
        self.assertEqual(summary["by_domain"][0]["domain"], "physics")

    def test_metrics_for_latest_snapshot(self):
        self._collect()
        self._collect()
        rows = self.storage.metrics_for(self.post.id)
        self.assertEqual(len(rows), 4)
        vk = [row for row in rows if row["platform"] == "vk"][0]
        self.assertEqual(vk["views"], 77)

    def test_error_isolated_per_platform(self):
        def boom(url, **kwargs):
            raise RuntimeError("network down")

        with patch.dict("os.environ", ENV, clear=False):
            collector = MetricsCollector(self.config, self.storage, http_get=boom)
            result = collector.collect(platforms=["vk"])
        self.assertEqual(result["targets"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["stored"], 0)
        self.assertEqual(self.storage.metrics_summary()["totals"]["samples"], 0)

    def test_format_summary(self):
        self._collect()
        text = format_metrics_summary(self.storage.metrics_summary())
        self.assertIn("Метрики площадок", text)
        self.assertIn("bluesky", text)
        empty = format_metrics_summary({"totals": {}, "by_platform": []})
        self.assertIn("Данных нет", empty)

    def test_metrics_by_style(self):
        self.storage.set_post_meta(self.post.id, "style_variant", "compact")
        self._collect()
        by_style = self.storage.metrics_by_style()
        self.assertEqual(len(by_style), 1)
        self.assertEqual(by_style[0]["variant"], "compact")
        self.assertEqual(by_style[0]["views"], 100 + 77 + 12)
        self.assertEqual(by_style[0]["posts"], 1)


if __name__ == "__main__":
    unittest.main()
