import json
import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.site import SiteBuilder
from science_pulse.sources.offline import OfflineBunkerSource
from science_pulse.storage import Storage


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={}, root=self.root)
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.source = OfflineBunkerSource(self.config)
        for index in range(3):
            post = self.source.synthesize(index)
            post.quality = post.quality_score()
            self.storage.add_post(post)
            self.storage.mark_published(post.id)
        self.builder = SiteBuilder(self.config, self.storage)

    def tearDown(self):
        self.temp.cleanup()

    def test_build_files(self):
        dist = self.builder.build()
        for name in ("index.html", "search.json", "graph.json", "sitemap.xml", "llms.txt", "llms-full.txt", "robots.txt", ".nojekyll"):
            self.assertTrue((dist / name).exists(), name)
        self.assertTrue((dist / "assets" / "style.css").exists())

    def test_index_contains_posts(self):
        dist = self.builder.build()
        index = (dist / "index.html").read_text(encoding="utf-8")
        posts = self.storage.list_posts(status="published")
        self.assertIn(posts[0].title, index)
        self.assertIn("Граф знаний", index)
        self.assertIn("PageRank", index)
        self.assertIn("search.json", index)

    def test_post_page_and_search(self):
        dist = self.builder.build()
        post = self.storage.list_posts(status="published")[0]
        page = (dist / "post" / f"{post.id}.html").read_text(encoding="utf-8")
        self.assertIn(post.title, page)
        self.assertIn("katex", page.lower())
        search = json.loads((dist / "search.json").read_text(encoding="utf-8"))
        self.assertTrue(any(item["id"] == post.id for item in search))

    def test_graph_links(self):
        dist = self.builder.build()
        graph = json.loads((dist / "graph.json").read_text(encoding="utf-8"))
        self.assertEqual(len(graph["nodes"]), 3)
        self.assertIsInstance(graph["links"], list)
        for node in graph["nodes"]:
            self.assertIn("pagerank", node)
            self.assertIn("x", node)
            self.assertIn("y", node)
            self.assertLess((node["x"] ** 2 + node["y"] ** 2) ** 0.5, 1.0)

    def _public_builder(self):
        config = Config(raw={"miniapp": {"public": True}}, root=self.root)
        config.ensure_dirs()
        return SiteBuilder(config, self.storage)

    def test_miniapp_hidden_by_default(self):
        """Пульт (pult.html) не публикуется на сайте, пока явно не разрешён."""
        dist = self.builder.build()
        self.assertFalse((dist / "pult.html").exists())
        index = (dist / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("pult.html", index)

    def test_miniapp_stale_page_removed_when_private(self):
        """Если публикацию отключили, устаревший pult.html удаляется при сборке."""
        self._public_builder().build()
        self.assertTrue((self.config.dist_dir / "pult.html").exists())
        self.builder.build()
        self.assertFalse((self.config.dist_dir / "pult.html").exists())

    def test_miniapp_page(self):
        dist = self._public_builder().build()
        pult = (dist / "pult.html").read_text(encoding="utf-8")
        self.assertIn("Пульт Science Pulse", pult)
        self.assertIn("mini-action", pult)
        self.assertIn("data-command=\"run\"", pult)

    def test_miniapp_platforms_and_language_toggle(self):
        dist = self._public_builder().build()
        pult = (dist / "pult.html").read_text(encoding="utf-8")
        self.assertIn("Площадки / Platforms", pult)
        self.assertIn('data-lang="en"', pult)
        self.assertIn("renderPlatforms", pult)
        self.assertIn('data-about="en"', pult)
        self.assertIn("TG_BOT_TOKEN", pult)


if __name__ == "__main__":
    unittest.main()
