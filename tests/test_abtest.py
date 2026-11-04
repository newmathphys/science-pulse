import tempfile
import unittest
from pathlib import Path

from science_pulse.abtest import (
    VARIANTS,
    ab_enabled,
    choose_variant,
    variant_style,
    variants_from_config,
)
from science_pulse.cards import render_card
from science_pulse.config import Config
from science_pulse.models import Post


class ABTestTests(unittest.TestCase):
    def test_choose_variant_deterministic(self):
        self.assertEqual(choose_variant("post-123"), choose_variant("post-123"))
        self.assertIn(choose_variant("post-123"), VARIANTS)

    def test_choose_variant_custom_list(self):
        self.assertIn(choose_variant("x", ("a", "b", "c")), {"a", "b", "c"})

    def test_variant_style(self):
        self.assertTrue(variant_style(None)["show_hook"])
        self.assertFalse(variant_style("compact")["show_hook"])
        self.assertEqual(variant_style("unknown"), variant_style("classic"))

    def test_config_helpers(self):
        self.assertFalse(ab_enabled(Config(raw={})))
        self.assertTrue(ab_enabled(Config(raw={"abtest": {"enabled": True}})))
        self.assertEqual(variants_from_config(Config(raw={"abtest": {"variants": ["a"]}})), ("a",))

    def test_render_card_variants(self):
        post = Post(
            id="p",
            domain="math",
            title="Тестовая тема с формулой",
            hook="Вопрос?",
            body="Длинный текст с формулой $x^2$ для проверки рендера карточки.",
            formula_plain="x^2",
            source_name="test",
        )
        with tempfile.TemporaryDirectory() as tmp:
            classic = render_card(post, out_path=Path(tmp) / "classic.png", variant="classic")
            compact = render_card(post, out_path=Path(tmp) / "compact.png", variant="compact")
        self.assertEqual(classic.width, 1080)
        self.assertEqual(classic.height, 1080)
        self.assertGreater(len(classic.data), 10_000)
        self.assertGreater(len(compact.data), 10_000)


if __name__ == "__main__":
    unittest.main()
