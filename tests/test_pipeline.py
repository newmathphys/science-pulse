import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.models import Post, PublishResult
from science_pulse.pipeline import Pipeline
from science_pulse.storage import Storage
from science_pulse.models import make_id


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

    def publish(self, item, card, site_url="", public_card_url="", video_url="", targets=None, video=False):
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
        self.config = Config(
            raw={"data_dir": "data", "dist_dir": "dist", "publish_min_interval_hours": 0},
            root=self.root,
        )
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.sources = FakeSources([post("m1", "math"), post("p1", "physics"), post("c1", "cs")])
        self.publishers = FakePublishers(self.storage)
        self.pipeline = Pipeline(self.config, self.storage, self.sources, self.publishers)

    def tearDown(self):
        self.temp.cleanup()

    def test_prereq_ready_accepts_canon_ids(self):
        parent = post("parent", "math")
        parent.id = make_id("history_canon", "euclid_gcd")
        self.storage.add_post(parent)
        self.storage.mark_published(parent.id)
        child = post("child", "cs")
        child.meta["prereq_ids"] = ["euclid_gcd"]
        self.assertTrue(self.pipeline._prereq_ready(child))

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

    def test_slot_guard_blocks_second_publish_within_interval(self):
        self.config.raw["publish_min_interval_hours"] = 3
        first = self.pipeline.publish_next()
        self.assertTrue(first["ok"])
        second = self.pipeline.publish_next()
        self.assertTrue(second.get("deferred"))
        self.assertEqual(second.get("reason"), "slot")
        forced = self.pipeline.publish_next(force=True)
        self.assertTrue(forced["ok"])

    def test_card_size_from_config_is_honored(self):
        """Смена `card.size` не должна отправлять в карантин каждый пост."""
        config = Config(raw={"data_dir": "data", "dist_dir": "dist",
                             "publish_min_interval_hours": 0,
                             "card": {"size": 240, "ssaa": 1, "engine": "pillow"}},
                        root=self.root)
        config.ensure_dirs()
        storage = Storage(config.db_path)
        pipeline = Pipeline(config, storage, self.sources, FakePublishers(storage))
        result = pipeline.publish_next()
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["card"].width, 240)
        self.assertEqual(storage.count("published"), 1)
        self.assertEqual(storage.count("rejected"), 0, "контур качества не должен заворачивать пост")

    def test_auto_quarantine_is_soft(self):
        """Брак на авто-публикации уходит в карантин, не валя прогон (exit 0)."""
        bad = Post(id="badcode", domain="cs", title="Битый код алгоритма",
                   body="Разбор алгоритма с кодом, который не парсится. " * 2,
                   code="def f(:\n    pass", source_name="test")
        self.sources.posts = [bad]
        self.assertEqual(self.pipeline.harvest(), 1)
        result = self.pipeline.publish_next()
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("quarantined"))
        self.assertEqual(self.storage.get_post("badcode").status, "rejected")
        self.assertEqual(self.storage.count("published"), 0)

    def test_run_retries_after_quarantine(self):
        """Брак в карантине не теряет слот: run() берёт следующий здоровый пост."""
        bad = Post(id="bad1", domain="cs", title="Битый код алгоритма",
                   body="Разбор алгоритма с кодом, который не парсится. " * 2,
                   code="def f(:\n    pass", source_name="test")
        bad.meta["priority"] = 100  # чтобы его выбрали первым
        good = post("good1", "math")
        self.sources.posts = [bad, good]
        self.pipeline.harvest()
        result = self.pipeline.run(build_site=False)
        self.assertTrue(result.get("ok"))
        self.assertFalse(result.get("quarantined"))
        self.assertEqual(result["post"].id, "good1")
        self.assertEqual(self.storage.get_post("bad1").status, "rejected")
        self.assertEqual(self.storage.count("published"), 1)

    def test_run_defers_when_d1_pull_fails(self):
        """Сбойный pull D1 не должен публиковать из пустой БД (иначе дубли-перевыпуск)."""
        from contextlib import contextmanager
        from unittest import mock

        @contextmanager
        def ok_guard(self, ttl_s=900):
            yield {"ok": True}

        self.sources.posts = [post("math1", "math")]
        with mock.patch.object(Pipeline, "d1_primary_enabled", return_value=True), \
                mock.patch.object(Pipeline, "state_guard", ok_guard), \
                mock.patch.object(Pipeline, "pull_state",
                                  return_value={"ok": False, "error": "boom"}):
            result = self.pipeline.run(build_site=False)
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("deferred"))
        self.assertEqual(result.get("reason"), "state")
        self.assertEqual(self.storage.count("published"), 0)

    def test_priority_post_is_chosen_first(self):
        """Пост с meta.priority>=100 (trend/pick) выходит вне общего порядка."""
        self.pipeline.harvest()
        physics = next(p for p in self.storage.list_posts(status="ready") if p.domain == "physics")
        self.storage.set_post_meta(physics.id, "priority", 100)
        chosen = self.pipeline.choose_next()
        self.assertEqual(chosen.id, physics.id)

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

    def _enable_hawkes(self):
        self.config.raw["hawkes"] = {"enabled": True, "beta_per_hour": 0.38, "eps": 0.45}

    def test_hawkes_gate_defers_instead_of_failing(self):
        """Отказ гейта Hawkes — отложенная публикация (ok=True), а не сбой.

        Иначе шаг `Run pipeline` в CI падал бы, а оператор получал ложный
        алерт `if: failure()` — при штатном поведении «подождать».
        """
        self._enable_hawkes()
        self.assertEqual(self.pipeline.harvest(), 3)
        self.pipeline.sota.record_hawkes_fire()
        result = self.pipeline.publish_next()
        self.assertTrue(result["ok"])
        self.assertTrue(result["deferred"])
        self.assertEqual(result["reason"], "hawkes")
        self.assertIsNone(result["post"])
        self.assertIn("Hawkes", result["error"])
        # Очередь не сгорела, публикаций нет.
        self.assertEqual(self.storage.count("ready"), 3)
        self.assertEqual(self.storage.count("published"), 0)
        self.assertEqual(self.publishers.calls, [])

    def test_hawkes_gate_is_soft_in_run(self):
        self._enable_hawkes()
        self.pipeline.sota.record_hawkes_fire()
        result = self.pipeline.run()
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("deferred"))
        self.assertEqual(self.storage.count("published"), 0)
        self.assertEqual(self.publishers.calls, [])

    def test_force_bypasses_maturity_gate(self):
        """Ручной `/force` публикует канон вопреки гейту зрелости (решение оператора)."""
        self.config.raw["maturity"] = {"enabled": True, "threshold": 100, "enforce_canon_only": True}
        canon = post("k1", "cs")
        canon.meta["canon_id"] = "kalman_filter"
        self.sources.posts = [canon]
        self.assertEqual(self.pipeline.harvest(), 1)
        deferred = self.pipeline.publish_next()
        self.assertTrue(deferred.get("deferred"))
        self.assertEqual(deferred.get("reason"), "maturity")
        self.assertEqual(self.storage.count("published"), 0)
        forced = self.pipeline.publish_next(force=True)
        self.assertTrue(forced["ok"], forced.get("error"))
        self.assertFalse(forced.get("deferred"))
        self.assertEqual(self.storage.count("published"), 1)

    def test_force_bypasses_hawkes_gate(self):
        self._enable_hawkes()
        self.pipeline.sota.record_hawkes_fire()
        forced = self.pipeline.publish_next(force=True)
        self.assertTrue(forced["ok"])
        self.assertFalse(forced.get("deferred"))
        self.assertEqual(forced["post"].domain, "math")
        self.assertEqual(self.storage.count("published"), 1)


if __name__ == "__main__":
    unittest.main()
