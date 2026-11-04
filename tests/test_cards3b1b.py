import tempfile
import unittest
from pathlib import Path

from science_pulse.cards3b1b import render_3b1b_plot, render_studio_card, typst_available
from science_pulse.models import Post


def make_post(domain="math"):
    return Post(
        id=f"{domain}1",
        domain=domain,
        title="Тестовая карточка 3Blue1Brown",
        hook="Зачем это нужно?",
        body="Проверка студийного рендера карточки с цветовым кодированием.",
        formula_plain="f(x)",
        source_name="test",
    )


class StudioCardTests(unittest.TestCase):
    def test_plot_palette_and_legend(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = render_3b1b_plot(make_post("math"), Path(tmp) / "plot.png")
            self.assertTrue(Path(info["plot_path"]).exists())
            self.assertEqual(len(info["legend"]), 3)

    def test_plot_all_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            for domain in ("math", "physics", "cs"):
                info = render_3b1b_plot(make_post(domain), Path(tmp) / f"{domain}.png")
                self.assertTrue(Path(info["plot_path"]).exists())

    def test_sequence_chart_is_content_aware(self):
        from science_pulse.cards3b1b import _extract_sequence

        post = make_post("math")
        post.hook = "Какой закон скрыт в последовательности 0,1,1,2,3,5,8,13,21,34,55,89,144?"
        seq = _extract_sequence(post)
        self.assertEqual(seq[:6], [0, 1, 1, 2, 3, 5])
        self.assertNotEqual(seq[-1], 144)  # ложная точка «144?» отброшена
        with tempfile.TemporaryDirectory() as tmp:
            info = render_3b1b_plot(post, Path(tmp) / "seq.png")
            labels = [label for _, label in info["legend"]]
            self.assertIn("Члены a(n)", labels)

    def test_plain_math_has_no_sequence(self):
        from science_pulse.cards3b1b import _extract_sequence

        self.assertEqual(_extract_sequence(make_post("math")), [])

    @unittest.skipUnless(typst_available(), "typst не установлен")
    def test_studio_card_all_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            for domain in ("math", "physics", "cs"):
                artifact = render_studio_card(make_post(domain), Path(tmp) / f"{domain}.png")
                self.assertIsNotNone(artifact)
                self.assertEqual((artifact.width, artifact.height), (1080, 1080))
                self.assertGreater(len(artifact.data), 10_000)

    def test_studio_card_none_without_typst(self):
        if typst_available():
            self.skipTest("typst установлен — проверка fallback не применима")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(render_studio_card(make_post("math"), Path(tmp) / "x.png"))


    def test_plot_family_is_content_aware(self):
        """Разные по смыслу посты получают разные графики (не один шаблон)."""
        from science_pulse.cards3b1b import _plot_family, render_3b1b_plot

        cases = [
            ("orbit", "N-body problem: орбита и тяготение", "Как движутся планеты вокруг Солнца?"),
            ("wave", "Квантовая волновая функция", "Что описывает волна де Бройля?"),
            ("decay", "Радиоактивный распад", "Что такое полураспад ядра?"),
            ("prob", "Нормальное распределение", "Почему вероятность описывают гауссовой кривой?"),
            ("sort", "Сложность сортировки", "Как растёт время алгоритма O(N log N)?"),
            ("growth", "Последовательность Фибоначчи", "Какой закон скрыт: 0,1,1,2,3,5,8,13,21,34,55,89,144?"),
            ("cells", "Conway's Game of Life", "Как устроен клеточный автомат?"),
        ]
        legends = set()
        for family, title, hook in cases:
            post = make_post("physics")
            post.title = title
            post.hook = hook
            post.body = hook
            self.assertEqual(_plot_family(post), family, title)
            with tempfile.TemporaryDirectory() as tmp:
                info = render_3b1b_plot(post, Path(tmp) / "plot.png")
            legends.add(tuple(label for _, label in info["legend"]))
        self.assertEqual(len(legends), len(cases), "графики должны отличаться")


if __name__ == "__main__":
    unittest.main()
