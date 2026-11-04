import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.curriculum import complexity_tier, format_curriculum, is_foundation, order_posts, sort_key
from science_pulse.models import Post
from science_pulse.pipeline import Pipeline
from science_pulse.sources.foundation import FoundationSource


def simple_post(post_id="c1", **meta):
    return Post(id=post_id, domain="math", title="Простая сумма чисел и площадь",
                body="Сумма и площадь фигуры. " * 12, formula_plain="a + b", meta=dict(meta))


def deep_post(post_id="c2"):
    return Post(id=post_id, domain="physics", title="Тензор кривизны и ковариантная производная",
                body="Тензор, многообразие, ковариантная производная, квантовая хромодинамика. " * 8,
                formula_latex=r"\int \nabla_\mu T^{\mu\nu} \, dV \otimes \mathcal{R}",
                formula_plain="∫ ∇_μ T^μν dV ⊗ R")


class CurriculumTests(unittest.TestCase):
    def test_foundation_node_gets_step_as_tier(self):
        post = FoundationSource(Config(raw={})).fetch(limit=1, cycle=0)[0]
        self.assertTrue(is_foundation(post))
        self.assertEqual(complexity_tier(post), post.meta["step"])

    def test_online_post_tier_in_range(self):
        tier = complexity_tier(simple_post())
        self.assertGreaterEqual(tier, 11)
        self.assertLessEqual(tier, 100)

    def test_deep_post_has_higher_tier(self):
        self.assertGreater(complexity_tier(deep_post()), complexity_tier(simple_post()))

    def test_order_posts_foundation_first(self):
        foundation = FoundationSource(Config(raw={})).fetch(limit=1, cycle=3)[0]
        posts = [simple_post("z1"), foundation, deep_post("z2")]
        ordered = order_posts(posts)
        self.assertEqual(ordered[0].id, foundation.id)
        self.assertTrue(is_foundation(ordered[0]))

    def test_sort_key_is_stable(self):
        post = simple_post("k1")
        self.assertEqual(sort_key(post), sort_key(post))

    def test_format_curriculum_rows(self):
        rows = format_curriculum([simple_post("f1")], limit=3)
        self.assertEqual(len(rows), 1)
        self.assertIn("tier", rows[0])
        self.assertIn("foundation", rows[0])


class PipelineOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(raw={}, root=Path(self.temp.name))
        self.config.ensure_dirs()
        self.pipeline = Pipeline(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def test_choose_next_prefers_foundation(self):
        source = FoundationSource(self.config)
        foundation = source.fetch(limit=1, cycle=0)[0]   # Пифагор, ступень 1
        self.pipeline.storage.add_post(foundation)
        self.pipeline.storage.add_post(simple_post("n1"))
        chosen = self.pipeline.choose_next()
        self.assertEqual(chosen.id, foundation.id)

    def test_choose_next_orders_by_tier_without_foundation(self):
        self.pipeline.storage.add_post(deep_post("d1"))
        self.pipeline.storage.add_post(simple_post("s1"))
        chosen = self.pipeline.choose_next()
        self.assertEqual(chosen.id, "s1")

    def test_choose_next_respects_domain(self):
        self.pipeline.storage.add_post(deep_post("phys1"))
        self.pipeline.storage.add_post(simple_post("math1"))
        chosen = self.pipeline.choose_next(domain="physics")
        self.assertEqual(chosen.domain, "physics")


if __name__ == "__main__":
    unittest.main()