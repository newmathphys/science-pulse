"""Инфографический explainer-фильм."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.explainer_film import (
    ExplainerScene,
    _counter_series,
    explainer_film_available,
    explainer_settings,
    render_explainer_film,
)
from science_pulse.models import Post
from science_pulse.voice import VoiceArtifact


def make_post() -> Post:
    return Post(
        id="amdahl1",
        domain="cs",
        title="Закон Амдала: предел ускорения",
        hook="Почему 10 процессоров не дают ×10?",
        body="Ускорение ограничено последовательной частью программы. " * 4,
        formula_plain="S = 1 / ((1 - P) + P / N)",
        source_name="Джин Амдал, 1967",
        meta={"scientist": "Джин Амдал", "era": "1967", "modern_application": "параллельные вычисления"},
    )


class ExplainerTests(unittest.TestCase):
    def test_settings(self):
        config = Config(raw={"explainer": {"width": 1080, "height": 1920, "fps": 24}})
        self.assertEqual(explainer_settings(config)["aspect"], "9:16")
        self.assertEqual(explainer_settings(config, "1:1")["aspect"], "1:1")

    def test_counter_is_deterministic(self):
        first = _counter_series(make_post())
        second = _counter_series(make_post())
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 4)
        self.assertGreater(first[-1], first[0])

    def test_scene_render(self):
        scene = ExplainerScene(make_post(), 360, 640)
        image = scene.render(1.0)
        self.assertEqual(image.size, (360, 640))

    @unittest.skipUnless(explainer_film_available(), "нужен ffmpeg")
    def test_render_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(raw={"explainer": {"width": 360, "height": 640, "fps": 6, "max_frames": 30}})
            artifact = VoiceArtifact(post_id="amdahl1", text="тест", mp3_path="", duration_s=3.0,
                                     words=[(0.0, 0.5, "тест")])
            out = Path(tmp) / "explainer.mp4"
            result = render_explainer_film(make_post(), out, config, aspect="9:16",
                                           artifact=artifact, max_seconds=3)
            self.assertIsNotNone(result)
            self.assertTrue(result.is_file())
            self.assertGreater(result.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
