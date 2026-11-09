import tempfile
import unittest
from pathlib import Path

from PIL import Image

from science_pulse.book_film import (
    BookFilmScene,
    book_film_available,
    book_film_settings,
    render_book_film,
)
from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.voice import VoiceArtifact


def make_post():
    return Post(
        id="book1",
        domain="math",
        title="Эйлер: тождество, связывающее пять констант",
        hook="Почему e, i, π, 1 и 0 встречаются в одной формуле?",
        body=(
            "Тождество Эйлера получается из формулы e^{iφ} = cos φ + i sin φ при φ = π. "
            "Оно связывает экспоненту, мнимую единицу, число π, единицу и ноль. "
            "Комплексные числа стали языком квантовой механики и теории сигналов."
        ),
        formula_latex=r"e^{i\pi} + 1 = 0",
        formula_plain="e^(iπ) + 1 = 0",
        source_name="test",
        meta={"section_num": "3.1", "era": "1748 г."},
    )


class BookFilmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={"book_film": {"fps": 6}}, root=self.root)
        self.config.ensure_dirs()

    def tearDown(self):
        self.temp.cleanup()

    def test_settings(self):
        square = book_film_settings(self.config, "1:1")
        vertical = book_film_settings(self.config, "9:16")
        self.assertEqual((square["width"], square["height"]), (1080, 1080))
        self.assertEqual((vertical["width"], vertical["height"]), (1080, 1080))

    def test_scene_frame_is_paper_book(self):
        scene = BookFilmScene(make_post(), 540, 540)
        try:
            image = scene.render(1.0)
            self.assertEqual(image.size, (540, 540))
            self.assertEqual(image.getpixel((2, 2)), (250, 248, 244))
            self.assertEqual(image.mode, "RGB")
        finally:
            scene.close()

    def test_vertical_frame(self):
        scene = BookFilmScene(make_post(), 270, 480)
        try:
            image = scene.render(0.5)
            self.assertEqual(image.size, (270, 480))
        finally:
            scene.close()

    @unittest.skipUnless(book_film_available(), "нужен ffmpeg")
    def test_render_short_film(self):
        artifact = VoiceArtifact(
            post_id="book1",
            text="Эйлер. Тождество связывает пять констант. Формула e в степени i пи плюс один равно нулю.",
            mp3_path="",
            duration_s=0.6,
            words=[(0.0, 0.2, "Эйлер."), (0.2, 0.4, "Тождество"), (0.4, 0.6, "констант.")],
        )
        output = self.root / "book.mp4"
        path = render_book_film(make_post(), output, self.config, artifact=artifact, max_seconds=0.6)
        self.assertIsNotNone(path)
        self.assertTrue(Path(path).is_file())
        self.assertGreater(Path(path).stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
