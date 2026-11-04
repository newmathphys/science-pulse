import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.constants import constants_used_by
from science_pulse.site import SiteBuilder
from science_pulse.sources.history_canon import HistoryCanonSource
from science_pulse.storage import Storage


class KnowledgePagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={}, root=self.root)
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        source = HistoryCanonSource(self.config)
        for index in range(6):
            post = source.fetch(limit=1, cycle=index)[0]
            self.storage.add_post(post)
            self.storage.mark_published(post.id)
        self.builder = SiteBuilder(self.config, self.storage)

    def tearDown(self):
        self.temp.cleanup()

    def test_scientists_page(self):
        dist = self.builder.build()
        page = (dist / "scientists.html").read_text(encoding="utf-8")
        self.assertIn("Досье учёных", page)
        self.assertIn("Пифагор", page)
        self.assertIn("Применение сегодня", page)
        self.assertIn("post/", page)

    def test_constants_page(self):
        dist = self.builder.build()
        page = (dist / "constants.html").read_text(encoding="utf-8")
        self.assertIn("Словарь физических величин", page)
        self.assertIn("Скорость света", page)
        self.assertIn("299792458", page)

    def test_topics_page_hubs(self):
        dist = self.builder.build()
        page = (dist / "topics.html").read_text(encoding="utf-8")
        self.assertIn("маршрут изучения", page)

    def test_constants_usage_links_posts(self):
        posts = self.storage.list_posts(status="published", limit=50)
        usage = constants_used_by(posts)
        # у Ньютона/MAXWELL из канона есть константы — связка должна найтись
        self.assertTrue(usage)

    def test_sitemap_includes_new_pages(self):
        dist = self.builder.build()
        sitemap = (dist / "sitemap.xml").read_text(encoding="utf-8")
        for name in ("scientists.html", "constants.html", "topics.html"):
            self.assertIn(name, sitemap)


if __name__ == "__main__":
    unittest.main()