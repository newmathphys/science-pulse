import tempfile
import unittest
from pathlib import Path
from unittest import mock

from science_pulse import voice as voice_mod
from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.voice import (
    VoiceArtifact,
    speech_text,
    synthesize,
    voice_available,
    voice_for_post,
    voice_settings,
)


def make_post(**meta):
    return Post(
        id="voice1",
        domain="physics",
        title="Шрёдингер: волновое уравнение",
        hook="Как одна формула описывает атомы?",
        body="В 1926 году Шрёдингер записал уравнение, описывающее эволюцию волновой функции. "
             "Оно объясняет уровни энергии атома, химическую связь и туннельный эффект.",
        formula_latex=r"i\hbar \partial_t \Psi = \hat{H}\Psi",
        formula_plain="iħ·∂Ψ/∂t = ĤΨ",
        source_name="Хроника Науки",
        meta=dict(meta),
    )


class SpeechTextTests(unittest.TestCase):
    def test_removes_latex_code_and_emoji(self):
        post = make_post(modern_application="квантовая химия, лазеры")
        post.body = "Текст $x^2$ и код `print(1)` и <b>тег</b> 🚀 дальше."
        text = speech_text(post)
        self.assertNotIn("$", text)
        self.assertNotIn("`", text)
        self.assertNotIn("<b>", text)
        self.assertNotIn("🚀", text)
        self.assertIn("квантовая химия", text)

    def test_includes_modern_application(self):
        post = make_post(modern_application="Sentinel-1: мониторинг вулканов")
        text = speech_text(post)
        self.assertIn("Применение сегодня", text)
        self.assertIn("Sentinel-1", text)

    def test_truncation_keeps_words(self):
        post = make_post()
        post.body = "Слово " * 400
        text = speech_text(post, max_chars=200)
        self.assertLessEqual(len(text), 215)  # текст + «Формула: …» в хвосте
        self.assertFalse(text.rstrip().endswith("Слов"))
        self.assertIn(".", text)

    def test_short_post_returns_text(self):
        self.assertGreater(len(speech_text(make_post())), 40)


class VoiceSettingsTests(unittest.TestCase):
    def test_defaults(self):
        settings = voice_settings(Config(raw={}))
        self.assertEqual(settings["engine"], "auto")
        self.assertEqual(settings["voice"], "ru-RU-SvetlanaNeural")
        self.assertFalse(settings["enabled"])

    def test_override(self):
        settings = voice_settings(Config(raw={"voice": {"enabled": True, "engine": "piper", "max_chars": 500}}))
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["engine"], "piper")
        self.assertEqual(settings["max_chars"], 500)


class SynthesizeTests(unittest.TestCase):
    @staticmethod
    def _fake_edge(text, out_mp3, voice, rate="+0%"):
        Path(out_mp3).write_bytes(b"ID3" + b"0" * 5000)
        return voice, [(0, 5_000_000, "Проверка"), (5_000_000, 5_000_000, "синтеза.")]

    def test_synthesize_with_fake_edge(self):
        config = Config(raw={"voice": {"enabled": True, "engine": "edge"}})
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(voice_mod, "_synthesize_edge", side_effect=self._fake_edge), \
                 mock.patch.object(voice_mod, "_to_voice_ogg", return_value=False):
                artifact = synthesize("Проверка синтеза речи", tmp, "p1", config)
            self.assertIsNotNone(artifact)
            self.assertEqual(artifact.engine, "edge")
            self.assertTrue(Path(artifact.mp3_path).is_file())

    def test_cache_hit_skips_synthesis(self):
        config = Config(raw={"voice": {"enabled": True, "engine": "edge"}})
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(voice_mod, "_synthesize_edge", side_effect=self._fake_edge), \
                 mock.patch.object(voice_mod, "_to_voice_ogg", return_value=False):
                first = synthesize("Один и тот же текст для кэша", tmp, "p2", config)
                with mock.patch.object(voice_mod, "_synthesize_edge",
                                       side_effect=AssertionError("не должен вызываться")):
                    second = synthesize("Один и тот же текст для кэша", tmp, "p2", config)
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertEqual(first.mp3_path, second.mp3_path)

    def test_fallback_does_not_poison_cache(self):
        """Сонификация не помечается кэш-ключом речи — иначе голос не вернётся."""
        config = Config(raw={"voice": {"enabled": True, "engine": "edge"}})
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(voice_mod, "_synthesize_edge", return_value=("", [])), \
                 mock.patch.object(voice_mod, "_to_voice_ogg", return_value=False):
                fallback = synthesize("Текст для сонификации", tmp, "p4", config, post=make_post())
            self.assertIsNotNone(fallback, "фоллбэк обязан дать аудио, а не падать")
            self.assertEqual(fallback.engine, "sonification_fallback")
            self.assertFalse(Path(tmp, "p4.key").exists(), "фоллбэк не пишет кэш-ключ")
            with mock.patch.object(voice_mod, "_synthesize_edge", side_effect=self._fake_edge), \
                 mock.patch.object(voice_mod, "_to_voice_ogg", return_value=False):
                real = synthesize("Текст для сонификации", tmp, "p4", config)
            self.assertIsNotNone(real)
            self.assertEqual(real.engine, "edge", "кэш не подменил речь сонификацией")

    def test_fallback_removes_stale_key(self):
        """Если ключ уже лежал от прошлого прогона — фоллбэк его снимает."""
        config = Config(raw={"voice": {"enabled": True, "engine": "edge"}})
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "p5.key").write_text("старый-ключ", encoding="utf-8")
            with mock.patch.object(voice_mod, "_synthesize_edge", return_value=("", [])), \
                 mock.patch.object(voice_mod, "_to_voice_ogg", return_value=False):
                synthesize("Текст", tmp, "p5", config, post=make_post())
            self.assertFalse(Path(tmp, "p5.key").exists(), "старый ключ снят")

    def test_failure_returns_none(self):
        config = Config(raw={"voice": {"enabled": True, "engine": "edge"}})
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(voice_mod, "_synthesize_edge", return_value=("", [])):
                self.assertIsNone(synthesize("Текст без движка", tmp, "p3", config))

    def test_voice_for_post(self):
        config = Config(raw={"voice": {"enabled": True, "engine": "edge"}})
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(voice_mod, "_synthesize_edge", side_effect=self._fake_edge), \
                 mock.patch.object(voice_mod, "_to_voice_ogg", return_value=False):
                artifact = voice_for_post(make_post(), config, out_dir=tmp)
            self.assertIsNotNone(artifact)
            self.assertEqual(artifact.post_id, "voice1")

    def test_voice_available_without_engine(self):
        config = Config(raw={"voice": {"engine": "piper", "piper_model": ""}})
        self.assertFalse(voice_available(config))


class TelegramVoiceTests(unittest.TestCase):
    def test_publisher_sends_voice(self):
        from science_pulse.publishers.telegram import TelegramPublisher

        config = Config(raw={
            "voice": {"enabled": True, "engine": "edge", "publish": "voice"},
            "telegram": {"channel_id": "@test", "admin_chat_id": "1"},
        })
        publisher = TelegramPublisher(config)
        artifact = VoiceArtifact(post_id="voice1", text="т", mp3_path="/tmp/a.mp3",
                                 ogg_path="/tmp/a.ogg", duration_s=30.0, engine="edge")
        with mock.patch.object(voice_mod, "voice_for_post", return_value=artifact), \
             mock.patch.object(publisher, "send_voice", return_value=True) as send_voice:
            meta = publisher._maybe_send_voice(make_post(), reply_to=5)
        self.assertEqual(meta["voice"], "sent")
        self.assertEqual(meta["voice_duration"], 30.0)
        send_voice.assert_called_once()

    def test_publisher_disabled_voice(self):
        from science_pulse.publishers.telegram import TelegramPublisher

        publisher = TelegramPublisher(Config(raw={"voice": {"enabled": False}, "telegram": {"channel_id": "@test"}}))
        self.assertEqual(publisher._maybe_send_voice(make_post(), reply_to=None), {})


if __name__ == "__main__":
    unittest.main()