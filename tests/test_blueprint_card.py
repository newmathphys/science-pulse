"""Дизайн `blueprint`: перекраска в миллиметровку, сетка, штамп и карточка."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from science_pulse.cards_blueprint import BG, GOLD, GRID_FINE, apply_blueprint, render_blueprint_card
from science_pulse.models import Post

PAPER = (250, 248, 244)


def make_post(post_id: str = "bp1") -> Post:
    return Post(
        id=post_id,
        domain="physics",
        title="Спутниковая интерферометрия и математика кадра",
        hook="Как матричная алгебра находит сдвиги земной коры из космоса?",
        body="Достаточно длинный текст научного разбора для валидации качества поста "
             "и книжной вёрстки карточки академической серии. Продолжение текста для объёма.",
        formula_latex=r"E = m c^2",
        source_name="Тест · Черчёж",
        meta={"visual_type": "standard_plot", "section_num": "7.1"},
    )


def palette(image: Image.Image):
    return {color for _, color in (image.getcolors(maxcolors=1_000_000) or [])}


def mean_red(image: Image.Image) -> float:
    data = image.convert("RGB").tobytes()
    return sum(data[0::3]) / (len(data) // 3)


class ApplyBlueprintTests(unittest.TestCase):
    def test_light_paper_becomes_deep_blue(self):
        out = apply_blueprint(Image.new("RGB", (216, 216), PAPER))
        self.assertEqual(out.size, (216, 216))
        self.assertLess(mean_red(out), 60, "светлая бумага уходит в глубокую синь")
        background = out.getpixel((5, 5))  # вне сетки (шаг 27) и штампа (справа сверху)
        # бумага 250/255 не чисто белая, поэтому тон-мап даёт оттенок рядом с BG
        for got, expected in zip(background, BG):
            self.assertLessEqual(abs(got - expected), 8, f"{background} не рядом с {BG}")

    def test_dark_ink_becomes_light_line(self):
        out = apply_blueprint(Image.new("RGB", (64, 64), (17, 17, 17)))
        pixel = out.getpixel((5, 5))
        self.assertGreater(pixel[0], 180, "тушь инвертируется в светлую линию")

    def test_grid_and_stamp_are_drawn(self):
        out = apply_blueprint(Image.new("RGB", (216, 216), PAPER))
        colors = palette(out)
        self.assertIn(GRID_FINE, colors, "миллиметровая сетка нарисована")
        self.assertIn(GOLD, colors, "штамп ГОСТ/IEEE нарисован")
        self.assertGreaterEqual(len(colors), 4)

    def test_label_is_used_in_stamp(self):
        plain = apply_blueprint(Image.new("RGB", (216, 216), PAPER), label="A")
        verbose = apply_blueprint(Image.new("RGB", (216, 216), PAPER), label="ГОСТ/IEEE · ЧЕРТЁЖ")
        self.assertNotEqual(plain.tobytes(), verbose.tobytes(), "подпись влияет на штамп")

    def test_deterministic(self):
        first = apply_blueprint(Image.new("RGB", (160, 160), PAPER))
        second = apply_blueprint(Image.new("RGB", (160, 160), PAPER))
        self.assertEqual(first.tobytes(), second.tobytes())


class RenderBlueprintCardTests(unittest.TestCase):
    def test_card_is_written_as_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "blueprint.png"
            artifact = render_blueprint_card(make_post(), target, size=360)
            self.assertIsNotNone(artifact, "книжная вёрстка доступна — карточка обязана собраться")
            path = Path(artifact.path)
            self.assertTrue(path.exists())
            self.assertEqual(artifact.width, 360)
            self.assertEqual(artifact.height, 360)
            self.assertEqual(artifact.data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(path.read_bytes(), artifact.data)
            with Image.open(path) as image:
                self.assertEqual(image.size, (360, 360))
                self.assertLess(mean_red(image), 140, "карточка перекрашена в синь")


if __name__ == "__main__":
    unittest.main()
