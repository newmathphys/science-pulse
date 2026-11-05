"""Moku3D: 5-актовая раскадровка, 3D-геометрия и сборка фильма."""

import tempfile
import unittest
from pathlib import Path

from science_pulse import moku_film
from science_pulse.config import Config
from science_pulse.models import Post


def make_post(domain: str = "physics", identifier: str = "film1") -> Post:
    return Post(
        id=identifier,
        domain=domain,
        title="Закон всемирного тяготения и его инвариант",
        hook="Как одна формула объяснила и падение яблока, и орбиту Луны?",
        body="Ньютон объединил земную механику и законы Кеплера в единый закон тяготения. " * 3,
        formula_latex="F = G m_1 m_2 / r^2",
        formula_plain="F = G · (m₁ · m₂) / r²",
        source_name="Фундамент Науки · Ньютон",
        meta={"section_num": "2.3", "concept": "тяготение"},
    )


class StoryboardTests(unittest.TestCase):
    def test_five_acts_with_exactly_one_line(self):
        acts = moku_film.storyboard(make_post())
        self.assertEqual(len(acts), moku_film.ACTS)
        self.assertEqual([item["roman"] for item in acts], list(moku_film.ACT_ROMAN))
        for index, item in enumerate(acts, start=1):
            self.assertEqual(item["act"], index)
            self.assertTrue(item["title"])
            self.assertTrue(item["line"].strip())
            self.assertNotIn("\n", item["line"], "в кадре ровно одна строка текста")
            self.assertLessEqual(len(item["line"]), moku_film.LINE_LIMIT)

    def test_acts_carry_hook_formula_example_and_task(self):
        acts = moku_film.storyboard(make_post())
        self.assertIn("яблок", acts[0]["line"])
        self.assertIn("F = G", acts[1]["line"])
        self.assertTrue(acts[3]["line"].strip())
        self.assertTrue(acts[4]["line"].strip())


class SceneTests(unittest.TestCase):
    def test_kind_by_domain(self):
        self.assertEqual(moku_film.Scene3D(make_post("physics")).kind, "physics")
        self.assertEqual(moku_film.Scene3D(make_post("math")).kind, "math")
        self.assertEqual(moku_film.Scene3D(make_post("cs")).kind, "cs")

    def test_physics_is_bounded_figure_eight(self):
        scene = moku_film.Scene3D(make_post("physics"))
        span = float(abs(scene.trajectory).max())
        self.assertLess(span, 2.5, "«восьмёрка» трёх тел должна оставаться в кадре")

    def test_frame_has_geometry_and_counter(self):
        scene = moku_film.Scene3D(make_post("physics"))
        data = scene.frame(3, 0.5, 0.5)
        self.assertIsNotNone(data["points"])
        self.assertTrue(data["trails"])
        self.assertIn("|v|", data["counter"])

    def test_math_switches_harmonics_in_act_four(self):
        scene = moku_film.Scene3D(make_post("math"))
        self.assertIn("n = 1", scene.frame(2, 0.5, 0.4)["counter"])
        self.assertIn("n = 3", scene.frame(4, 0.5, 0.8)["counter"])

    def test_projection_is_perspective(self):
        import numpy as np

        rotation = moku_film._rotation(0.0, 0.0)
        points = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, -1.0]])
        xs, ys, depth = moku_film._project(points, rotation, 100, 100)
        self.assertEqual(len(xs), 2)
        self.assertGreater(float(depth[0]), float(depth[1]))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_render_frames_count_and_sizes(self):
        settings = {"size": 120, "fps": 6, "seconds_per_act": 0.5, "audio": False}
        out_dir = self.root / "frames"
        frames = moku_film.render_frames(make_post("math"), out_dir, settings)
        self.assertEqual(frames, int(round(0.5 * moku_film.ACTS * 6)))
        pngs = sorted(out_dir.glob("frame_*.png"))
        self.assertEqual(len(pngs), frames)
        from PIL import Image

        with Image.open(pngs[0]) as image:
            self.assertEqual(image.size, (120, 120))

    @unittest.skipUnless(moku_film.film_available(), "ffmpeg не установлен")
    def test_short_film_is_valid_mp4(self):
        self.config.raw["moku3d"] = {"size": 160, "fps": 8, "seconds_per_act": 0.6, "audio": True}
        target = self.root / "film.mp4"
        path = moku_film.render_moku3d_short_film(make_post("cs"), target, config=self.config)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 20_000)
        self.assertFalse((self.root / "_moku3d_film1").exists(), "рабочие кадры убираются")

    def test_settings_defaults(self):
        settings = moku_film.moku3d_settings(None)
        self.assertEqual(settings["size"], moku_film.SIZE)
        self.assertEqual(settings["fps"], moku_film.FPS)
        self.assertEqual(settings["seconds_per_act"], moku_film.SECONDS_PER_ACT)
        self.assertEqual(settings["aspect"], "1:1")
        self.assertEqual((settings["width"], settings["height"]), (moku_film.SIZE, moku_film.SIZE))

    def test_frame_size_aspects(self):
        self.assertEqual(moku_film.frame_size(720, "1:1"), (720, 720))
        self.assertEqual(moku_film.frame_size(720, "9:16"), (720, 1280))
        width, height = moku_film.frame_size(1080, "9:16")
        self.assertEqual((width, height), (1080, 1920))
        self.assertEqual(width % 2, 0)    # yuv420p требует чётные стороны
        self.assertEqual(height % 2, 0)

    def test_render_frames_vertical_aspect(self):
        settings = {"size": 144, "aspect": "9:16", "fps": 6, "seconds_per_act": 0.5,
                    "audio": False, "width": 144, "height": 256}
        out_dir = self.root / "frames_vertical"
        frames = moku_film.render_frames(make_post("math", "vert1"), out_dir, settings)
        pngs = sorted(out_dir.glob("frame_*.png"))
        self.assertEqual(len(pngs), frames)
        from PIL import Image

        with Image.open(pngs[0]) as image:
            self.assertEqual(image.size, (144, 256))


    def test_aspect_argument_overrides_config(self):
        self.config.raw["moku3d"] = {"size": 540, "aspect": "1:1"}
        square = moku_film.moku3d_settings(self.config)
        vertical = moku_film.moku3d_settings(self.config, aspect="9:16")
        self.assertEqual((square["width"], square["height"]), (540, 540))
        self.assertEqual((vertical["width"], vertical["height"]), (540, 960))
        self.assertEqual(self.config.raw["moku3d"]["aspect"], "1:1", "конфиг не мутируется")

    def test_vertical_film_has_separate_cache(self):
        self.config.raw["moku3d"] = {"size": 720, "aspect": "1:1"}
        out_dir = self.root / "films"
        out_dir.mkdir(parents=True, exist_ok=True)
        cached = out_dir / "vert2_9x16.mp4"
        cached.write_bytes(b"0" * 25_000)
        found = moku_film.film_for_post(make_post("math", "vert2"), self.config,
                                        out_dir=out_dir, aspect="9:16")
        self.assertEqual(found, cached, "вертикальный кэш отдельный от квадратного")


if __name__ == "__main__":
    unittest.main()
