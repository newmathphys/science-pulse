"""Регрессии визуала и речи: без заглушек, «даэнэ» и случайных чисел."""
from __future__ import annotations

import unittest
from pathlib import Path

from science_pulse.book_film import BookFilmScene
from science_pulse.config import load_config
from science_pulse.storage import Storage
from science_pulse.voice import build_film_script, verified_example


def post(pid: str):
    return Storage(load_config().db_path).get_post(pid)


class VisualRegressionTests(unittest.TestCase):
    def test_speech_has_no_robot_labels_or_bad_abbreviation(self):
        for pid in ("b063d20371654588", "0212a505f66fee75"):
            text = build_film_script(post(pid))
            self.assertNotIn("даэнэ", text.lower())
            for label in ("Вопрос:", "Суть:", "Формула:", "Проверка:", "Применение:", "Раздел "):
                self.assertNotIn(label, text)
            self.assertIn("до нашей эры" if pid.startswith("b0") else "года", text)

    def test_verified_example_is_real_and_not_year(self):
        pyth = verified_example(post("b063d20371654588"))
        self.assertIn("трём и четырём", pyth)
        self.assertNotIn("2026", pyth)
        newton = verified_example(post("0212a505f66fee75"))
        self.assertIn("девять", newton)
        self.assertNotIn("2026", newton)

    def test_source_has_no_fake_formula_placeholder(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("science_pulse/book_film.py", "science_pulse/cards_academic.py"):
            text = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("величина в формуле", text)
            self.assertNotIn("скорость света", text)

    def test_scene_has_drawing_not_empty(self):
        scene = BookFilmScene(post("b063d20371654588"), 540, 540)
        try:
            image = scene.render(0.35 * scene.duration)
            # Центральная зона не должна быть пустой бумагой.
            crop = image.crop((90, 120, 450, 400))
            colors = crop.getcolors(maxcolors=1_000_000) or []
            non_paper = sum(count for count, color in colors if color != (250, 248, 244))
            self.assertGreater(non_paper, 500)
        finally:
            scene.close()


if __name__ == "__main__":
    unittest.main()
