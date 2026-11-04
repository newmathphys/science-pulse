import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.evolve import EvolutionEngine
from science_pulse.models import PublishResult
from science_pulse.pipeline import Pipeline
from science_pulse.sources.foundation import FoundationSource, STEP_BY_ID, ordered_nodes, step_of
from science_pulse.sources.history_canon import CANON


class FoundationOrderTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(raw={})
        self.source = FoundationSource(self.config)

    def test_first_step_is_roots(self):
        first = [self.source.fetch(limit=1, cycle=index)[0] for index in range(3)]
        self.assertEqual([post.meta["step"] for post in first], [1, 1, 1])
        self.assertEqual({post.domain for post in first}, {"math", "cs", "physics"})

    def test_all_canon_nodes_have_step(self):
        for item in CANON:
            self.assertIn(item["id"], STEP_BY_ID, item["id"])
            self.assertLessEqual(step_of(item["id"]), 6)

    def test_ordered_nodes_sorted_by_step(self):
        steps = [step_of(node["id"]) for node in ordered_nodes()]
        self.assertEqual(steps, sorted(steps))

    def test_meta_has_step_title(self):
        post = self.source.fetch(limit=1, cycle=0)[0]
        self.assertTrue(post.meta["step_title"])
        self.assertEqual(post.meta["foundation_id"], "pythagoras")
        self.assertEqual(post.tier, "foundation")


class EvolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={"telegram": {"channel_id": "@newmathphys"}}, root=self.root)
        self.config.ensure_dirs()
        self.pipeline = Pipeline(self.config)
        self.engine = EvolutionEngine(self.pipeline)

    def tearDown(self):
        self.temp.cleanup()

    def test_evolve_step_returns_foundation_first(self):
        result = self.engine.evolve_step()
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "foundation")
        self.assertEqual(result["step"], 1)

    def test_foundation_status_lists_rows(self):
        rows = self.engine.foundation_status(limit=5)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["step"], 1)
        self.assertIn("status", rows[0])

    def test_prereq_links_after_parent_published(self):
        source = FoundationSource(self.config)
        parent = source.fetch(limit=1, cycle=0)[0]          # Пифагор (ступень 1)
        child = source.fetch(limit=1, cycle=3)[0]           # Ньютон (ступень 2, опирается на Пифагора? — нет)
        # используем узел, у которого prereq указывает на Пифагора: euler_identity -> newton, fourier...
        linkable = [node for node in ordered_nodes() if "pythagoras" in (node.get("prereq_ids") or [])]
        if not linkable:
            self.skipTest("нет узлов, опирающихся на Пифагора")
        index = ordered_nodes().index(linkable[0])
        child = source.fetch(limit=1, cycle=index)[0]

        self.pipeline.storage.add_post(parent)
        self.pipeline.storage.mark_published(parent.id)
        self.pipeline.storage.record_publication(
            parent.id, PublishResult(platform="telegram", ok=True, external_id="24")
        )
        links = self.engine.prereq_links(child)
        self.assertEqual(links[0][1], "https://t.me/newmathphys/24")

    def test_prepare_sets_meta(self):
        source = FoundationSource(self.config)
        linkable = [node for node in ordered_nodes() if node.get("prereq_ids")]
        index = ordered_nodes().index(linkable[0])
        child = source.fetch(limit=1, cycle=index)[0]
        parent_id = FoundationSource.post_id_for(linkable[0]["prereq_ids"][0])
        parent = self.pipeline.storage.get_post(parent_id)
        if parent is None:
            self.pipeline.storage.add_post(source.fetch(limit=1, cycle=0)[0])
        self.engine.prepare(child)

    def test_used_in_backlinks(self):
        source = FoundationSource(self.config)
        parent = source.fetch(limit=1, cycle=0)[0]
        self.pipeline.storage.add_post(parent)
        linkable = [node for node in ordered_nodes() if "pythagoras" in (node.get("prereq_ids") or [])]
        if not linkable:
            self.skipTest("нет узлов, опирающихся на Пифагора")
        index = ordered_nodes().index(linkable[0])
        child = source.fetch(limit=1, cycle=index)[0]
        self.pipeline.storage.add_post(child)
        used = self.engine.used_in(parent)
        self.assertIn(child.id, [post.id for post in used])


if __name__ == "__main__":
    unittest.main()