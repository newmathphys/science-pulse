import unittest

from science_pulse.models import Post
from science_pulse.visual_language import colorized_formula_html, legend_html, symbol_colors, symbols_for_post


def post(formula="F = G · m / r²", **meta):
    return Post(
        id="v1", domain="physics", title="Гравитация",
        hook="Почему?", body="Тело и поле. " * 20,
        formula_plain=formula, meta=dict(meta),
    )


class VisualLanguageTests(unittest.TestCase):
    def test_same_symbol_same_color(self):
        colors = symbol_colors(post())
        self.assertEqual(colors.get("F"), colors.get("F"))
        self.assertIn("F", colors)

    def test_explicit_symbols_win(self):
        item = post(symbols={"m": "масса", "r": "расстояние"})
        self.assertEqual(symbols_for_post(item), ["m", "r"])

    def test_formula_is_colorized_without_html_leak(self):
        html = colorized_formula_html(post())
        self.assertIn('class="sym"', html)
        self.assertIn("--sym-color", html)
        self.assertNotIn("<script>", html)

    def test_legend_has_chips(self):
        html = legend_html(post())
        self.assertIn("sym-chip", html)
        self.assertIn("sym-legend", html)


if __name__ == "__main__":
    unittest.main()
