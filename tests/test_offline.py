import unittest

from science_pulse.config import Config
from science_pulse.sources.offline import OfflineBunkerSource


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.source = OfflineBunkerSource(Config(raw={}))

    def test_deterministic(self):
        first = self.source.synthesize(7)
        second = self.source.synthesize(7)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.formula_latex, second.formula_latex)

    def test_unique_cycles(self):
        posts = [self.source.synthesize(index) for index in range(20)]
        ids = {post.id for post in posts}
        titles = {post.title for post in posts}
        self.assertEqual(len(ids), 20)
        self.assertGreaterEqual(len(titles), 10)

    def test_posts_valid(self):
        for index in range(12):
            post = self.source.synthesize(index)
            self.assertEqual(post.validate(), [])
            self.assertTrue(post.formula_plain)
            self.assertIn(post.domain, {"math", "physics", "cs"})

    def test_fetch_limit(self):
        posts = self.source.fetch(limit=3, cycle=5)
        self.assertEqual(len(posts), 3)


if __name__ == "__main__":
    unittest.main()
