import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.models import Post, PublishResult
from science_pulse.pipeline import Pipeline
from science_pulse.storage import Storage


def post(identifier, domain):
    bodies = {
        "math": "Теорема Пифагора связывает катеты и гипотенузу прямоугольного треугольника: $x^2 + y^2 = z^2$. Доказательство опирается на площади квадратов.",
        "physics": "Квантовый осциллятор описывает колебания частицы в потенциале $V(x)=x^2/2$. Энергия квантуется, а волновые функции выражаются через полиномы Эрмита.",
        "cs": "Быстрая сортировка делит массив относительно опорного элемента. Средняя сложность алгоритма $O(n \\log n)$, а рекурсия заменяется явным стеком.",
    }
    return Post(
        id=identifier,
        domain=domain,
        title=f"Тестовая тема {identifier}",
        hook="Почему это работает?",
        body=bodies[domain],
        formula_latex="x^2 + y^2 = z^2" if domain == "math" else "E = h * nu" if domain == "physics" else "O(n log n)",
        formula_plain="x^2 + y^2 = z^2" if domain == "math" else "E = h * nu" if domain == "physics" else "O(n log n)",
        source_name="fake",
        source_url="https://example.org",
    )


class FakeSources:
    def __init__(self, posts):
        self.posts = posts
        self.sources = {}

    def fetch(self, limit_per_source=2, domains=None, include_offline=True):
        allowed = set(domains or ["math", "physics", "cs"])
        return [item for item in self.posts if item.domain in allowed]

    def status(self):
        return []


class FakePublishers:
    def __init__(self, storage):
        self.storage = storage
        self.calls = []

    def publish(self, item, card, site_url="", public_card_url="", targets=None, video=False):
        self.calls.append(item.id)
        result = PublishResult(platform="fake", ok=True, external_id="42")
        self.storage.record_publication(item.id, result)
        return [result]

    def available_platforms(self):
        return ["fake"]

    def status(self):
        return [{"name": "fake", "enabled": True, "available": True}]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=self.root)
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.sources = FakeSources([post("m1", "math"), post("p1", "physics"), post("c1", "cs")])
        self.publishers = FakePublishers(self.storage)
        self.pipeline = Pipeline(self.config, self.storage, self.sources, self.publishers)

    def tearDown(self):
        self.temp.cleanup()

    def test_dry_run_renders_without_publishing(self):
        result = self.pipeline.run(dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(Path(result["card"].path).exists())
        self.assertEqual(self.storage.count("published"), 0)
        self.assertEqual(self.storage.count("ready"), 3)
        self.assertEqual(self.publishers.calls, [])
        self.assertTrue((self.config.dist_dir / "index.html").exists())

    def test_publish_and_round_robin(self):
        first = self.pipeline.publish_next()
        self.assertTrue(first["ok"])
        self.assertEqual(first["post"].domain, "math")
        second = self.pipeline.publish_next()
        self.assertEqual(second["post"].domain, "physics")
        third = self.pipeline.publish_next()
        self.assertEqual(third["post"].domain, "cs")
        self.assertEqual(self.storage.count("published"), 3)

    def test_pause(self):
        self.storage.kv_set("paused", "1")
        result = self.pipeline.publish_next()
        self.assertFalse(result["ok"])
        self.assertIn("паузе", result["error"])
        forced = self.pipeline.publish_next(force=True)
        self.assertTrue(forced["ok"])

    def test_no_platforms_does_not_burn_queue(self):
        class NoPlatforms(FakePublishers):
            def available_platforms(self):
                return []

        pipeline = Pipeline(self.config, self.storage, self.sources, NoPlatforms(self.storage))
        result = pipeline.publish_next()
        self.assertFalse(result["ok"])
        self.assertIn("площадок", result["error"])
        self.assertEqual(self.storage.count("ready"), 3)
        self.assertEqual(self.storage.count("failed"), 0)

    def test_quality_gate_rejects_short_post(self):
        bad = Post(id="bad", domain="math", title="Коротко", body="мало", source_name="x")
        self.sources.posts = [bad]
        added = self.pipeline.harvest()
        self.assertEqual(added, 0)


if __name__ == "__main__":
    unittest.main()
