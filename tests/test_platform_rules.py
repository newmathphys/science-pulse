import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.platforms_info import PlatformRules, format_limits
from science_pulse.publishers.base import PublishContext, context_rules
from science_pulse.storage import Storage
from science_pulse.video import video_available
from science_pulse.voice import build_audiogram_mp4


def make_post():
    return Post(
        id="rules1",
        domain="math",
        title="Теорема Пифагора и метрика пространства",
        hook="Почему формула из VI века работает в 3D-движках?",
        body="В прямоугольном треугольнике квадрат гипотенузы равен сумме квадратов катетов. "
             "Это задаёт евклидову норму вектора и метрику пространства.",
        formula_latex=r"a^2 + b^2 = c^2",
        source_name="Хроника Науки",
    )


class PlatformRulesTests(unittest.TestCase):
    def test_defaults_match_spec(self):
        rules = PlatformRules()
        self.assertEqual(rules.limit("telegram"), 1024)
        self.assertEqual(rules.limit("threads"), 500)
        self.assertEqual(rules.limit("bluesky"), 300)
        self.assertEqual(rules.limit("discord", "max_embed_chars"), 4096)
        self.assertEqual(rules.limit("mastodon"), 500)
        self.assertEqual(rules.limit("vk"), 16384)

    def test_audio_modes_default(self):
        rules = PlatformRules()
        self.assertEqual(rules.audio_mode("telegram"), "auto")
        self.assertEqual(rules.audio_mode("discord"), "file")
        self.assertEqual(rules.audio_mode("mastodon"), "file")
        for platform in ("threads", "bluesky", "vk"):
            self.assertEqual(rules.audio_mode(platform), "link")

    def test_set_changes_limit(self):
        rules = PlatformRules()
        rules.set("threads", "max_caption_chars", 600)
        self.assertEqual(rules.limit("threads"), 600)
        rules.set("telegram", "audio_mode", "audio")
        self.assertEqual(rules.audio_mode("telegram"), "audio")

    def test_set_validates(self):
        rules = PlatformRules()
        with self.assertRaises(KeyError):
            rules.set("myspace", "max_caption_chars", 100)
        with self.assertRaises(KeyError):
            rules.set("threads", "unknown_param", 100)
        with self.assertRaises(ValueError):
            rules.set("threads", "audio_mode", "telepathy")

    def test_override_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(raw={}, root=Path(tmp))
            config.ensure_dirs()
            storage = Storage(config.db_path)
            rules = PlatformRules.load(storage, config)
            rules.set("threads", "max_caption_chars", 700)
            rules.save(storage)
            reloaded = PlatformRules.load(storage, config)
            self.assertEqual(reloaded.limit("threads"), 700)

    def test_config_yaml_overrides(self):
        config = Config(raw={"platform_rules": {"bluesky": {"max_caption_chars": 400}}})
        rules = PlatformRules.load(None, config)
        self.assertEqual(rules.limit("bluesky"), 400)

    def test_reset(self):
        rules = PlatformRules()
        rules.set("vk", "max_caption_chars", 100)
        rules.reset()
        self.assertEqual(rules.limit("vk"), 16384)

    def test_format_limits(self):
        text = format_limits(PlatformRules())
        self.assertIn("telegram", text)
        self.assertIn("threads", text)
        self.assertIn("/limits set", text)


class ContextRulesTests(unittest.TestCase):
    def test_context_rules_fallback(self):
        config = Config(raw={"platform_rules": {"threads": {"max_caption_chars": 555}}})
        self.assertEqual(context_rules(PublishContext(), config).limit("threads"), 555)

    def test_context_rules_from_context(self):
        rules = PlatformRules()
        rules.set("threads", "max_caption_chars", 321)
        self.assertEqual(context_rules(PublishContext(rules=rules), Config(raw={})).limit("threads"), 321)


class PublisherLimitTests(unittest.TestCase):
    def test_bluesky_text_respects_override(self):
        from science_pulse.publishers.bluesky import BlueskyPublisher

        publisher = BlueskyPublisher(Config(raw={}))
        rules = PlatformRules()
        rules.set("bluesky", "max_caption_chars", 120)
        text = publisher._text(make_post(), PublishContext(site_url="https://x.org"), rules)
        self.assertLessEqual(len(text), 120)

    def test_bluesky_text_within_generous_limit_keeps_site(self):
        from science_pulse.publishers.bluesky import BlueskyPublisher

        publisher = BlueskyPublisher(Config(raw={}))
        rules = PlatformRules()
        rules.set("bluesky", "max_caption_chars", 260)
        text = publisher._text(make_post(), PublishContext(site_url="https://x.org"), rules)
        self.assertIn("https://x.org", text)

    def test_bluesky_link_mode_adds_audio_link(self):
        from science_pulse.publishers.bluesky import BlueskyPublisher

        publisher = BlueskyPublisher(Config(raw={}))
        text = publisher._text(make_post(), PublishContext(site_url="https://x.org"), PlatformRules())
        self.assertIn("Аудио:", text)
        self.assertIn("post/rules1.html", text)

    def test_bluesky_off_mode_has_no_audio(self):
        from science_pulse.publishers.bluesky import BlueskyPublisher

        publisher = BlueskyPublisher(Config(raw={}))
        rules = PlatformRules()
        rules.set("bluesky", "audio_mode", "off")
        text = publisher._text(make_post(), PublishContext(site_url="https://x.org"), rules)
        self.assertNotIn("Аудио:", text)


class AudiogramTests(unittest.TestCase):
    @unittest.skipUnless(video_available(), "ffmpeg не установлен")
    def _fixtures(self, work: Path):
        import subprocess

        from PIL import Image

        card = work / "card.png"
        Image.new("RGB", (1080, 1080), (250, 248, 244)).save(card)
        audio = work / "audio.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=2", "-b:a", "128k", str(audio)], check=False)
        return card, audio

    @unittest.skipUnless(video_available(), "ffmpeg не установлен")
    def test_build_audiogram_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            card, audio = self._fixtures(work)
            out = work / "audiogram.mp4"
            self.assertTrue(build_audiogram_mp4(card, audio, out))
            self.assertGreater(out.stat().st_size, 1000)

    @unittest.skipUnless(video_available(), "ffmpeg не установлен")
    def test_build_audiogram_with_wave(self):
        """Живая осциллограмма (showwaves) собирается и картинка реально меняется."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            card, audio = self._fixtures(work)
            out = work / "wave.mp4"
            self.assertTrue(build_audiogram_mp4(card, audio, out, wave=True, wave_color="#1E3A8A"))
            # извлекаем два кадра: они должны отличаться (волна движется)
            frames = []
            for index, moment in enumerate(("0.2", "1.2")):
                frame = work / f"f{index}.png"
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", moment,
                                "-i", str(out), "-frames:v", "1", str(frame)], check=False)
                frames.append(frame.read_bytes() if frame.is_file() else b"")
            self.assertNotEqual(frames[0], frames[1], "осциллограмма должна двигаться")

    @unittest.skipUnless(video_available(), "ffmpeg не установлен")
    def test_build_audiogram_without_wave_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            card, audio = self._fixtures(work)
            out = work / "static.mp4"
            self.assertTrue(build_audiogram_mp4(card, audio, out, wave=False))

    def test_hex_to_ffmpeg(self):
        from science_pulse.voice import _hex_to_ffmpeg

        self.assertEqual(_hex_to_ffmpeg("#1E3A8A"), "0x1E3A8A")
        self.assertEqual(_hex_to_ffmpeg("9F1239"), "0x9F1239")
        self.assertEqual(_hex_to_ffmpeg(""), "0x1E3A8A")


if __name__ == "__main__":
    unittest.main()