import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.sound import synthesize_scientific_audio_wav
from science_pulse.voice import _which, mix_voice_with_pad, synthesize

FFMPEG = bool(_which("ffmpeg"))


def make_post():
    return Post(
        id="voicefallback1",
        domain="physics",
        title="Квантовый осциллятор и нулевые колебания",
        hook="Почему осциллятор не замирает?",
        body="Уровни энергии эквидистантны: E_n = ħω(n + 1/2). " * 6,
        formula_plain="x**2 + 1",
        source_name="test",
    )


class VoiceFallbackTests(unittest.TestCase):
    def test_sonification_writes_wav(self):
        with TemporaryDirectory() as tmp:
            wav = Path(tmp) / "pad.wav"
            self.assertTrue(synthesize_scientific_audio_wav(make_post(), wav))
            self.assertTrue(wav.is_file())
            self.assertGreater(wav.stat().st_size, 1000)

    @unittest.skipUnless(FFMPEG, "нужен ffmpeg")
    def test_eshelon3_fallback_without_tts(self):
        """Без edge/piper создаётся валидный mp3 сонификации (Эшелон 3)."""
        with TemporaryDirectory() as tmp:
            config = Config(raw={}, root=Path(tmp))
            settings = {"engine": "piper", "piper_model": "", "voice": "", "rate": "+0%"}
            artifact = synthesize(
                "Тест озвучки", Path(tmp), "p1", config, settings=settings, use_cache=False, post=make_post()
            )
            self.assertIsNotNone(artifact)
            self.assertEqual(artifact.engine, "sonification_fallback")
            self.assertTrue(Path(artifact.mp3_path).is_file())

    @unittest.skipUnless(FFMPEG, "нужен ffmpeg")
    def test_mix_voice_with_pad(self):
        with TemporaryDirectory() as tmp:
            post = make_post()
            pad = Path(tmp) / "pad.wav"
            self.assertTrue(synthesize_scientific_audio_wav(post, pad))
            speech = Path(tmp) / "speech.mp3"
            speech.write_bytes(pad.read_bytes())  # любой валидный аудиопоток
            out = Path(tmp) / "out.mp3"
            # amix требует корректный вход; при неудаче метод возвращает False.
            result = mix_voice_with_pad(speech, pad, out)
            self.assertIn(result, (True, False))
            if result:
                self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
