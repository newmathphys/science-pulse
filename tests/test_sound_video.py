import tempfile
import unittest
import wave
from pathlib import Path

from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.sound import DEFAULT_SECONDS, SAMPLE_RATE, sonify
from science_pulse.video import FRAME_COUNT, render_video, video_available, video_settings


def make_post(domain="math", **meta):
    return Post(
        id=f"media_{domain}",
        domain=domain,
        title="Ряд Фурье и гармоники сигнала",
        hook="Как сумма гармоник даёт кривую?",
        body="Разложение в ряд Фурье собирает функцию из синусов. Это основа обработки сигналов.",
        formula_latex=r"f(x) = \sum_{k=1}^{n} \frac{\sin(kx)}{k}",
        formula_plain="f(x) = ∑ sin(kx)/k",
        source_name="Тест · Медиа",
        meta=dict(meta),
    )


class SoundTests(unittest.TestCase):
    def test_sonify_creates_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = sonify(make_post(), Path(tmp) / "sound.wav")
            self.assertTrue(Path(info["path"]).is_file())
            self.assertEqual(info["sample_rate"], SAMPLE_RATE)
            with wave.open(info["path"], "rb") as handle:
                self.assertEqual(handle.getframerate(), SAMPLE_RATE)
                self.assertGreater(handle.getnframes(), 1000)

    def test_sonify_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = sonify(make_post(), Path(tmp) / "a.wav")
            second = sonify(make_post(), Path(tmp) / "b.wav")
            self.assertEqual(Path(first["path"]).read_bytes(), Path(second["path"]).read_bytes())

    def test_sonify_all_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            for domain in ("math", "physics", "cs"):
                info = sonify(make_post(domain), Path(tmp) / f"{domain}.wav")
                self.assertTrue(Path(info["path"]).is_file(), domain)
                self.assertGreater(Path(info["path"]).stat().st_size, 10_000, domain)


class VideoTests(unittest.TestCase):
    def test_video_settings_defaults(self):
        settings = video_settings(Config(raw={}))
        self.assertEqual(settings["every_nth_post"], 3)
        self.assertEqual(settings["frames"], FRAME_COUNT)
        self.assertTrue(settings["with_sound"])

    @unittest.skipUnless(video_available(), "ffmpeg не установлен")
    def test_render_video_with_sound(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = render_video(make_post("physics"), Path(tmp) / "video.mp4", seconds=2.0, frames=8)
            self.assertIsNotNone(out)
            self.assertTrue(Path(out).is_file())
            self.assertGreater(Path(out).stat().st_size, 5_000)

    @unittest.skipUnless(video_available(), "ffmpeg не установлен")
    def test_render_video_cs_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = render_video(make_post("cs"), Path(tmp) / "video.mp4", seconds=2.0, frames=8, with_sound=False)
            self.assertIsNotNone(out)


if __name__ == "__main__":
    unittest.main()