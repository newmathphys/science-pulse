import unittest

from science_pulse.config import Config
from science_pulse.publishers.base import build_rich_telegram_caption
from science_pulse.sources.history_canon import CANON, HistoryCanonSource


class HistoryCanonTests(unittest.TestCase):
    def setUp(self):
        self.source = HistoryCanonSource(Config(raw={}))

    def test_canon_is_valid(self):
        for index in range(len(CANON)):
            posts = self.source.fetch(limit=1, cycle=index)
            self.assertEqual(len(posts), 1)
            post = posts[0]
            self.assertEqual(post.validate(), [])
            self.assertTrue(post.formula_plain)
            self.assertIn(post.domain, {"math", "physics", "cs"})
            self.assertGreaterEqual(len(post.body), 300)

    def test_exhausted(self):
        self.assertEqual(self.source.fetch(limit=2, cycle=len(CANON)), [])

    def test_deterministic(self):
        first = self.source.fetch(limit=1, cycle=1)[0]
        second = self.source.fetch(limit=1, cycle=1)[0]
        self.assertEqual(first.id, second.id)

    def test_caption(self):
        post = self.source.fetch(limit=1, cycle=0)[0]
        caption = build_rich_telegram_caption(post, 1024, "https://example.org")
        self.assertNotIn("$", caption)
        self.assertGreaterEqual(len(caption), 450)
        self.assertLessEqual(len(caption), 1024)


if __name__ == "__main__":
    unittest.main()
