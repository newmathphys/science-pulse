"""Мониторинг changelog'ов площадок."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.platform_watch import (
    format_watch_report,
    parse_cloudflare,
    parse_rss,
    parse_telegram,
    parse_telegram_web,
    parse_threads,
    watch_platforms,
)


class ParserTests(unittest.TestCase):
    def test_telegram(self):
        result = parse_telegram("<h2>Recent changes</h2> August 24, 2026 Bot API 10.3 Rich Messages")
        self.assertIn("Bot API 10.3", result["latest"])

    def test_threads(self):
        result = parse_threads("Changelog (66) Search Changelog Nov 3, 2026 Added oEmbed support. Oct 30, 2026 Added AI label.")
        self.assertIn("Nov 3, 2026", result["latest"])
        self.assertIn("oEmbed", result["latest"])
        self.assertNotIn("Get notified", result["latest"])

    def test_telegram_web(self):
        page = (
            '<time datetime="2024-03-18T10:00:00+00:00"></time>'
            '<div class="tgme_widget_message_text">New WebK feature</div>'
        )
        result = parse_telegram_web(page)
        self.assertIn("2024-03-18", result["latest"])
        self.assertIn("New WebK feature", result["latest"])

    def test_cloudflare(self):
        result = parse_cloudflare("2026-10-22 Changed Hyperdrive. 2026-09-28 Updated v8.")
        self.assertIn("2026-10-22", result["latest"])

    def test_rss(self):
        xml = "<rss><channel><item><title>Actions update</title><pubDate>Mon, 02 Nov 2026 15:00:00 +0000</pubDate></item></channel></rss>"
        result = parse_rss(xml)
        self.assertIn("Actions update", result["latest"])


class WatchTests(unittest.TestCase):
    def _http(self, text: str):
        def get(url, timeout=30):
            return type("R", (), {"text": text})()
        return get

    def test_baseline_and_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(raw={}, root=Path(tmp))
            state = Path(tmp) / "watch.json"

            def get(url, timeout=30):
                if "telegram" in url:
                    return type("R", (), {"text": "Recent changes August 24, 2026 Bot API 10.3"})()
                if "threads" in url:
                    return type("R", (), {"text": "Search Changelog Nov 3, 2026 Added oEmbed."})()
                if "cloudflare" in url:
                    return type("R", (), {"text": "2026-10-22 Changed Hyperdrive."})()
                if "WebK_ru" in url:
                    return type("R", (), {"text": '<time datetime="2024-03-18T10:00:00+00:00"></time><div class="tgme_widget_message_text">WebK update</div>'})()
                return type("R", (), {"text": "<rss><channel><item><title>Actions</title></item></channel></rss>"})()

            first = watch_platforms(config, http_get=get, state_path=state)
            self.assertFalse(first["changed"])
            self.assertTrue(all(item.get("baseline") for item in first["sources"]))

            second = watch_platforms(config, http_get=get, state_path=state)
            self.assertFalse(second["changed"])

            def changed(url, timeout=30):
                if "telegram" in url:
                    return type("R", (), {"text": "Recent changes September 1, 2026 Bot API 10.4"})()
                return get(url, timeout=timeout)

            third = watch_platforms(config, http_get=changed, state_path=state)
            self.assertIn("Telegram Bot API", third["changed"])
            self.assertIn("Мониторинг API", format_watch_report(third))

    def test_error_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(raw={}, root=Path(tmp))

            def broken(url, timeout=30):
                raise TimeoutError("нет сети")

            report = watch_platforms(config, http_get=broken, state_path=Path(tmp) / "watch.json")
            self.assertTrue(report["errors"])
            self.assertEqual(len(report["sources"]), 5)


if __name__ == "__main__":
    unittest.main()
