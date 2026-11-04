import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config, load_config
from science_pulse.models import Post, make_id
from science_pulse.state_export import StateSync
from science_pulse.storage import Storage


class ModelsDirectTests(unittest.TestCase):
    def test_make_id_is_deterministic(self):
        self.assertEqual(make_id("history_canon", "pythagoras"), make_id("history_canon", "pythagoras"))
        self.assertNotEqual(make_id("history_canon", "pythagoras"), make_id("history_canon", "euclid_gcd"))

    def test_post_validate_catches_problems(self):
        bad = Post(id="x1", domain="math", title="Коротко", body="мало")
        self.assertTrue(bad.validate())
        good = Post(
            id="x2", domain="physics",
            title="Закон сохранения энергии в замкнутой системе",
            body="Энергия замкнутой системы сохраняется: она лишь переходит из одной формы в другую. " * 2,
            formula_plain="E = const",
        )
        self.assertEqual(good.validate(), [])

    def test_quality_score_bounds(self):
        rich = Post(id="q1", domain="cs", title="Быстрая сортировка и её сложность",
                    body="Разбор алгоритма. " * 20, formula_plain="O(n log n)",
                    code="def f(): pass", source_url="https://example.org", tier="online")
        self.assertGreater(rich.quality_score(), 0.8)
        poor = Post(id="q2", domain="cs", title="Короткий пост без формулы",
                    body="Небольшой текст без формулы и кода, но длиннее ста двадцати символов.", tier="offline")
        self.assertLess(poor.quality_score(), rich.quality_score())

    def test_post_roundtrip_row(self):
        post = Post(id="r1", domain="math", title="Теорема Пифагора и метрика",
                    body="Текст разбора. " * 10, formula_plain="a²+b²=c²", meta={"step": 1})
        restored = Post.from_row(dict(post.to_row()) | {"published_at": "", "status": "ready",
                                                        "card_path": "", "card_file_id": ""})
        self.assertEqual(restored.id, post.id)
        self.assertEqual(restored.meta.get("step"), 1)
        self.assertEqual(restored.label, post.label)

    def test_properties(self):
        post = Post(id="p1", domain="physics", title="Физика: волны и поля", body="Текст. " * 20)
        self.assertEqual(post.emoji, "⚛️")
        self.assertIn("#физика", post.hashtags)
        self.assertTrue(post.plain_title)


class ConfigDirectTests(unittest.TestCase):
    def test_load_from_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text(
                "schedule: [\"08:00\", \"20:00\"]\ndomains: [\"math\"]\ncard:\n  size: 1080\n"
                "max_queue: 42\nlow_water: 5\n", encoding="utf-8")
            config = load_config(root=root)
            self.assertEqual(config.schedule, ["08:00", "20:00"])
            self.assertEqual(config.domains, ["math"])
            self.assertEqual(config.max_queue, 42)
            self.assertEqual(config.low_water, 5)

    def test_ensure_dirs_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=Path(tmp))
            config.ensure_dirs()
            self.assertTrue(config.db_path.parent.is_dir())
            self.assertTrue(config.cards_dir.is_dir())
            self.assertTrue(config.dist_dir.is_dir())

    def test_platform_enabled_defaults(self):
        config = Config(raw={"platforms": {"telegram": {"enabled": True}}})
        self.assertTrue(config.platform_enabled("telegram"))
        self.assertFalse(config.platform_enabled("unknown_platform"))

    def test_site_base_url_priority(self):
        config = Config(raw={"site_base_url": "https://site.example/"})
        self.assertEqual(config.site_base_url, "https://site.example")


class StateExportDirectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(raw={}, root=Path(self.temp.name))
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_export_sql_contains_schema_and_rows(self):
        post = Post(id="s1", domain="math", title="Тестовая запись для экспорта",
                    body="Текст. " * 20, formula_plain="x = 1")
        self.storage.add_post(post)
        sync = StateSync(self.config, self.storage)
        sql = sync.export_sql()
        self.assertIn("CREATE TABLE IF NOT EXISTS posts", sql)
        self.assertIn("INSERT OR REPLACE INTO posts", sql)
        self.assertIn("s1", sql)

    def test_snapshot_and_import_are_idempotent(self):
        post = Post(id="s2", domain="cs", title="Идемпотентность импорта состояния",
                    body="Текст. " * 20, formula_plain="O(n)")
        self.storage.add_post(post)
        snapshot = self.storage.snapshot()
        self.assertIn("posts", snapshot)
        first = self.storage.import_rows(snapshot)
        second = self.storage.import_rows(snapshot)
        self.assertEqual(first, second)
        self.assertEqual(self.storage.get_post("s2").id, "s2")


if __name__ == "__main__":
    unittest.main()