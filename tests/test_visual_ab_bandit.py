"""Умная A/B-ротация дизайнов: бандит Томпсона, рейтинг и переключение."""

import random
import tempfile
import unittest
from pathlib import Path

from science_pulse import themes
from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.storage import Storage


BODIES = {
    "p_blue": "Инженерный чертёж показывает геометрию задачи в синей миллиметровке со штампом ГОСТ. " * 3,
    "p_acad": "Книжная серия верстает параграф как страницу университетского учебника с полями и колонтитулом. " * 3,
    "p_moku": "Короткометражный фильм ведёт зрителя по пяти актам и показывает живую геометрию уравнения. " * 3,
}


def make_post(identifier: str, theme: str | None = None, domain: str = "math") -> Post:
    meta = {"design_variant": {"theme": theme, "archetype": "standard_plot"}} if theme else {}
    return Post(
        id=identifier,
        domain=domain,
        title=f"Тема {identifier} и её инвариант",
        hook="Почему это работает?",
        body=BODIES.get(identifier, f"Разбор {identifier}: отдельный текст разбора для метрик. " * 3),
        formula_latex="x^2 + y^2 = z^2",
        formula_plain="x² + y² = z²",
        source_name="Тест",
        meta=meta,
    )


class ThemeRotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(raw={"card": {"theme": "auto"}}, root=Path(self.temp.name))
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.storage.connect()

    def tearDown(self):
        self.temp.cleanup()

    def test_auto_returns_known_theme(self):
        for _ in range(12):
            self.assertIn(themes.choose_theme(self.storage, self.config), themes.THEMES)

    def test_auto_keeps_diversity(self):
        """Один дизайн не идёт больше MAX_STREAK раз подряд на этапе обучения."""
        picks = [themes.choose_theme(self.storage, self.config, rng=random.Random(seed))
                 for seed in range(60)]
        longest, current = 1, 1
        for previous, following in zip(picks, picks[1:]):
            current = current + 1 if previous == following else 1
            longest = max(longest, current)
        self.assertLessEqual(longest, themes.MAX_STREAK)

    def test_fixed_theme_wins_over_bandit(self):
        ok, _ = themes.set_theme(self.storage, "blueprint")
        self.assertTrue(ok)
        self.assertEqual(themes.effective_theme(self.storage, self.config), "blueprint")
        self.assertEqual(themes.theme_for_post(self.storage, self.config), "blueprint")

    def test_set_theme_auto_and_unknown(self):
        self.assertTrue(themes.set_theme(self.storage, "auto")[0])
        self.assertEqual(themes.effective_theme(self.storage, self.config), "auto")
        ok, message = themes.set_theme(self.storage, "нет-такого")
        self.assertFalse(ok)
        self.assertIn("Неизвестный", message)

    def test_legacy_names_are_normalized(self):
        self.assertEqual(themes.normalize("neon"), "3b1b")
        self.assertEqual(themes.normalize("book"), "academic")
        self.assertEqual(themes.normalize("film"), "moku3d")

    def test_reward_changes_win_rate(self):
        before = themes.win_rates(self.storage)["moku3d"]
        for _ in range(6):
            themes.record_reward(self.storage, "moku3d", success=True)
        after = themes.win_rates(self.storage)["moku3d"]
        self.assertGreater(after, before)

    def test_design_stats_aggregate_metrics(self):
        self.storage.add_post(make_post("p_blue", "blueprint"))
        self.storage.add_post(make_post("p_acad", "academic"))
        self.storage.add_metrics("p_blue", "telegram", views=100, likes=10, replies=2)
        self.storage.add_metrics("p_acad", "telegram", views=10, likes=0, replies=0)
        rows = {item["theme"]: item for item in themes.design_stats(self.storage)}
        self.assertEqual(rows["blueprint"]["posts"], 1)
        self.assertEqual(rows["blueprint"]["avg_views"], 100.0)
        self.assertEqual(rows["blueprint"]["avg_likes"], 10.0)
        self.assertGreater(rows["blueprint"]["index_pct"], rows["academic"]["index_pct"])
        self.assertEqual(rows["blueprint"]["measured"], 1)

    def test_table_marks_leader_and_mode(self):
        self.storage.add_post(make_post("p_moku", "moku3d"))
        self.storage.add_metrics("p_moku", "telegram", views=500, likes=40, replies=5)
        table = themes.format_design_table(self.storage, self.config)
        self.assertIn("АНАЛИЗ ЭФФЕКТИВНОСТИ ДИЗАЙНОВ", table)
        self.assertIn("moku3d", table)
        self.assertIn("ЛИДЕР", table)
        plain = themes.format_design_table(self.storage, self.config, html=False)
        self.assertNotIn("<b>", plain)


if __name__ == "__main__":
    unittest.main()
