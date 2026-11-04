"""Тесты радара мировых новостей (Trending Radar) — без сети."""

import json
import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.storage import Storage
import logging

from science_pulse.trending import (
    TrendItem,
    TrendingRadar,
    classify_domain,
    format_trending,
    heat_score,
    keyword_hits,
)

HN_TOP_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
NOW = 1_800_000_000.0


def _hn_item(title, score, comments, age_hours):
    return {
        "type": "story",
        "title": title,
        "score": score,
        "descendants": comments,
        "time": NOW - age_hours * 3600,
        "url": f"https://example.com/{abs(hash(title))}",
    }


class FakeHTTP:
    """Фейковый HTTP: отдаёт заранее заданные ответы по URL."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        for key, value in self.routes.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"неожиданный URL: {url}")


class TrendingTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)  # тесты проверяют graceful degradation
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(raw={"data_dir": "data"}, root=Path(self.temp.name))
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self.temp.cleanup()

    def test_heat_score_rewards_fresh_and_popular(self):
        fresh = heat_score(100, 50, 1)
        stale = heat_score(100, 50, 50)
        self.assertGreater(fresh, stale)
        self.assertAlmostEqual(heat_score(0, 0, 10), 0.0)

    def test_classify_domain_and_relevance(self):
        self.assertEqual(classify_domain("A new proof of the prime conjecture"), "math")
        self.assertEqual(classify_domain("Quantum entanglement in black holes"), "physics")
        self.assertEqual(classify_domain("New sorting algorithm with better complexity"), "cs")
        self.assertIsNone(classify_domain("WTF Ubuntu?", strict=True))
        self.assertEqual(keyword_hits("proof of a theorem"), 2)

    def test_hackernews_parses_metrics(self):
        routes = {
            HN_TOP_URL: [1, 2],
            "/item/1.json": _hn_item("A proof of the twin prime conjecture", 300, 120, 2),
            "/item/2.json": _hn_item("Just some chatter", 500, 200, 1),
        }
        radar = TrendingRadar(self.config, self.storage, http_get=FakeHTTP(routes), now=lambda: NOW)
        items = radar.hackernews(limit=5)
        self.assertEqual(len(items), 2)
        proof = next(item for item in items if "prime" in item.title)
        self.assertEqual(proof.likes, 300)
        self.assertEqual(proof.comments, 120)
        self.assertEqual(proof.domain, "math")
        self.assertGreater(proof.relevance, 0)

    def test_scan_prefers_relevant_and_caches(self):
        routes = {
            HN_TOP_URL: [1, 2, 3],
            "/item/1.json": _hn_item("Ubuntu release notes", 900, 400, 1),
            "/item/2.json": _hn_item("New proof in number theory", 40, 10, 3),
            "/item/3.json": _hn_item("Quantum computing milestone", 30, 5, 5),
        }
        radar = TrendingRadar(self.config, self.storage, http_get=FakeHTTP(routes), now=lambda: NOW)
        items = radar.scan(top=3, translate=False)
        self.assertTrue(items)
        # научные (relevance > 0) должны идти раньше ненаучного «Ubuntu»
        self.assertGreater(items[0].relevance, 0)
        cached = json.loads(self.storage.kv_get("trending_candidates"))
        self.assertEqual(len(cached), len(items))
        self.assertIn("heat", cached[0])

    def test_scan_survives_network_failure(self):
        radar = TrendingRadar(self.config, self.storage, http_get=FakeHTTP({}), now=lambda: NOW)
        self.assertEqual(radar.scan(top=3, translate=False), [])

    def test_to_post_and_format(self):
        radar = TrendingRadar(self.config, self.storage, http_get=FakeHTTP({}), now=lambda: NOW)
        item = TrendItem(
            title="Новая теорема о простых числах",
            url="https://example.com/x",
            source="Hacker News",
            domain="math",
            likes=640,
            comments=185,
            heat=96.0,
            relevance=2,
        )
        post = radar.to_post(item)
        self.assertEqual(post.domain, "math")
        self.assertTrue(post.title)
        self.assertEqual(post.source_url, "https://example.com/x")
        report = format_trending([item], "ru")
        self.assertIn("640", report)
        self.assertIn("/pick 1", report)
        self.assertIn("ТОП МИРОВЫХ", report)
        self.assertEqual(format_trending([], "ru"), "Радар ничего не нашёл (нет сети или источники молчат).")


if __name__ == "__main__":
    unittest.main()
