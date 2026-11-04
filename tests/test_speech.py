import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config, parse_git_remote
from science_pulse.voice import math_to_spoken_russian, speech_text


def make_post(domain="cs"):
    from science_pulse.models import Post

    return Post(
        id="spoken1",
        domain=domain,
        title="Сортировка за O(N log N) и теорема Δφ",
        hook="Почему быстрая сортировка лучше O(N²)?",
        body="Сложность O(N log N) против O(N²). Энергия E = mc², постоянная ℏ и предел ≥ 0.",
        formula_latex=r"E = mc^2, \quad T = O(N \log N)",
        formula_plain="E = mc², T = O(N log N)",
        source_name="Тест · Диктор",
    )


class SpokenMathTests(unittest.TestCase):
    def test_complexity_phrases(self):
        self.assertEqual(math_to_spoken_russian("O(N log N)"), "о большое от эн логарифм эн")
        self.assertEqual(math_to_spoken_russian("O(n log n)"), "о большое от эн логарифм эн")
        self.assertEqual(math_to_spoken_russian("O(N²)"), "о большое от эн квадрат")
        self.assertEqual(math_to_spoken_russian("O(n^2)"), "о большое от эн квадрат")
        self.assertEqual(math_to_spoken_russian("O(log N)"), "о большое от логарифм эн")
        self.assertEqual(math_to_spoken_russian("O(1)"), "о от единицы")

    def test_greek_and_constants(self):
        self.assertIn("дельта фи", math_to_spoken_russian("Δφ"))
        self.assertIn("пси", math_to_spoken_russian("Ψ(x)"))
        self.assertIn("лямбда", math_to_spoken_russian("λ"))
        self.assertIn("аш с чертой", math_to_spoken_russian("ℏ"))
        self.assertIn("пи", math_to_spoken_russian("π"))
        self.assertIn("це в квадрате", math_to_spoken_russian("c²"))

    def test_relations(self):
        self.assertIn("больше либо равно", math_to_spoken_russian("x ≥ 0"))
        self.assertIn("приближённо равно", math_to_spoken_russian("π ≈ 3"))
        self.assertIn("умножить на", math_to_spoken_russian("2 · 3"))

    def test_no_math_left_untouched(self):
        text = math_to_spoken_russian("O(N log N) ≥ Δφ · ℏ c²")
        for symbol in ("O(", "≥", "Δ", "ℏ", "²", "·"):
            self.assertNotIn(symbol, text, symbol)

    def test_plain_text_unchanged(self):
        plain = "Теорема Пифагора связывает катеты и гипотенузу."
        self.assertEqual(math_to_spoken_russian(plain), plain)

    def test_speech_text_uses_spoken_math(self):
        text = speech_text(make_post("cs"))
        self.assertIn("о большое от эн логарифм эн", text)
        self.assertIn("це в квадрате", text)
        self.assertNotIn("O(N", text)


class GitRemoteTests(unittest.TestCase):
    def test_ssh_remote(self):
        self.assertEqual(parse_git_remote("git@github.com:newmathphys/science-pulse.git"),
                         "https://newmathphys.github.io/science-pulse")

    def test_https_remote(self):
        self.assertEqual(parse_git_remote("https://github.com/newmathphys/science-pulse"),
                         "https://newmathphys.github.io/science-pulse")

    def test_kern_is_ignored(self):
        self.assertEqual(parse_git_remote("git@github.com:newmathphys/kern.git"), "")

    def test_garbage_returns_empty(self):
        self.assertEqual(parse_git_remote("не url"), "")
        self.assertEqual(parse_git_remote(""), "")

    def test_config_detects_from_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            import subprocess

            subprocess.run(["git", "init", "-q"], cwd=root, check=False)
            subprocess.run(["git", "remote", "add", "origin",
                            "git@github.com:newmathphys/science-pulse.git"], cwd=root, check=False)
            self.assertEqual(Config(raw={}, root=root).site_base_url,
                             "https://newmathphys.github.io/science-pulse")

    def test_config_prefers_explicit_value(self):
        self.assertEqual(Config(raw={"site_base_url": "https://example.org"}).site_base_url,
                         "https://example.org")


class DirectVideoUploadTests(unittest.TestCase):
    def test_bluesky_uploads_video_blob(self):
        from unittest import mock

        from science_pulse import voice as voice_mod
        from science_pulse.publishers.bluesky import BlueskyPublisher

        publisher = BlueskyPublisher(Config(raw={}))
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "a.mp4"
            video.write_bytes(b"\x00" * 2048)
            with mock.patch.object(voice_mod, "audiogram_for_post", return_value=video), \
                 mock.patch("science_pulse.publishers.bluesky.requests.post") as post:
                post.return_value.json.return_value = {"blob": {"$type": "blob", "ref": {"$link": "x"}}}
                blob = publisher._upload_video(make_post("physics"), {"Authorization": "Bearer t"})
            self.assertIsNotNone(blob)
            # видео уходит как video/mp4 прямо байтами, без публичного URL сайта
            self.assertEqual(post.call_args.kwargs["headers"]["Content-Type"], "video/mp4")

    def test_vk_video_save_flow(self):
        from unittest import mock

        from science_pulse import voice as voice_mod
        from science_pulse.publishers.vk import VKPublisher

        publisher = VKPublisher(Config(raw={"vk": {"group_id": "123"}}))
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "a.mp4"
            video.write_bytes(b"\x00" * 2048)
            with mock.patch.object(voice_mod, "audiogram_for_post", return_value=video), \
                 mock.patch("science_pulse.publishers.vk.requests.get") as get, \
                 mock.patch("science_pulse.publishers.vk.requests.post") as post:
                get.return_value.json.return_value = {"response": {"upload_url": "https://up.vk", "video_id": 777}}
                attachment = publisher._upload_video(make_post("physics"))
            self.assertEqual(attachment, "video-123_777")
            self.assertTrue(post.called)


if __name__ == "__main__":
    unittest.main()