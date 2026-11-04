import json
import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.site import SiteBuilder, _e
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

    def test_index_is_curriculum_matrix(self):
        """Главная — карта ступеней канона (без vis-network и «прыгающих кружков»)."""
        dist = self.builder.build()
        index = (dist / "index.html").read_text(encoding="utf-8")
        self.assertIn("СТУПЕНЬ", index)
        self.assertIn("passport", index)
        self.assertIn("class=\"node locked\"", index)
        self.assertNotIn("vis-network", index)
        self.assertIn("search.json", index)

    def test_index_contains_posts(self):
        dist = self.builder.build()
        index = (dist / "index.html").read_text(encoding="utf-8")
        posts = self.storage.list_posts(status="published")
        self.assertIn(posts[0].title, index)
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


    def test_pwa_assets(self):
        dist = self.builder.build()
        for name in ("manifest.webmanifest", "sw.js"):
            self.assertTrue((dist / name).exists(), name)
        manifest = json.loads((dist / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "Science Pulse")
        self.assertTrue(any(icon["sizes"] == "192x192" for icon in manifest["icons"]))
        index = (dist / "index.html").read_text(encoding="utf-8")
        self.assertIn("manifest.webmanifest", index)
        self.assertIn("serviceWorker", index)

    def test_bibtex_export(self):
        dist = self.builder.build()
        bib = (dist / "bibtex.bib").read_text(encoding="utf-8")
        posts = self.storage.list_posts(status="published")
        self.assertIn("@misc{sciencepulse_", bib)
        self.assertIn(posts[0].id, bib)
        index = (dist / "index.html").read_text(encoding="utf-8")
        self.assertIn("bibtex.bib", index)

    def test_symbol_search_index(self):
        """В индекс поиска попадают формулы — искать можно по символам."""
        dist = self.builder.build()
        index = (dist / "index.html").read_text(encoding="utf-8")
        post = self.storage.list_posts(status="published")[0]
        token = post.formula_plain.strip()[:12]
        self.assertTrue(token, "у поста должна быть формула")
        self.assertIn(_e(token), index)
        search = json.loads((dist / "search.json").read_text(encoding="utf-8"))
        self.assertTrue(any(item.get("formula") for item in search))


    def test_post_page_has_interactive_sandbox(self):
        """На странице поста — интерактивная лаборатория (Canvas + ползунки)."""
        dist = self.builder.build()
        post = self.storage.list_posts(status="published")[0]
        page = (dist / "post" / f"{post.id}.html").read_text(encoding="utf-8")
        self.assertIn('id="sandbox-canvas"', page)
        self.assertIn('id="sandbox-x"', page)
        self.assertIn('id="sandbox-y"', page)
        self.assertIn('id="param-a"', page)
        self.assertIn('id="param-b"', page)
        self.assertIn("getContext('2d')", page)

    def test_poincare_atlas(self):
        """Главная содержит интерактивный диск Пуанкаре и данные маршрутов."""
        dist = self.builder.build()
        index = (dist / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="poincare"', index)
        self.assertIn("id=\"poincare-path\"", index)
        self.assertIn("mobius", index)
        payload = json.loads((dist / "poincare.json").read_text(encoding="utf-8"))
        self.assertEqual(len(payload["nodes"]), 30)
        self.assertTrue(payload["edges"])
        for node in payload["nodes"]:
            self.assertLess(node["x"] ** 2 + node["y"] ** 2, 1.0)
        self.assertTrue(all(payload["paths"][node["id"]] for node in payload["nodes"]))

    def test_flashcards_page(self):
        dist = self.builder.build()
        page = (dist / "flashcards.html").read_text(encoding="utf-8")
        self.assertIn("Карточки для повторения", page)
        self.assertIn("<details", page)
        index = (dist / "index.html").read_text(encoding="utf-8")
        self.assertIn("flashcards.html", index)


if __name__ == "__main__":
    unittest.main()
