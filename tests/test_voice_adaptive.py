"""Адаптивная цепочка TTS: лимиты, cooldown и восстановление."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from science_pulse import voice as voice_mod
from science_pulse.config import Config
from science_pulse.voice import synthesize, voice_engine_status


def _write_mp3(path: Path) -> None:
    path.write_bytes(b"ID3" + b"0" * 5000)


class AdaptiveVoiceTests(unittest.TestCase):
    def _config(self, tmp: Path, **voice: object) -> Config:
        model = tmp / "piper.onnx"
        model.write_bytes(b"fake")
        raw = {
            "voice": {
                "enabled": True,
                "engine": "auto",
                "piper_model": str(model),
                "priority": ["edge", "piper", "google_tts", "espeak", "sonification"],
                "google_fallback": True,
                **voice,
            }
        }
        return Config(raw=raw, root=tmp)

    def test_edge_429_switches_to_piper_and_blocks_edge(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            config = self._config(tmp)
            out = config.data_dir / "audio"

            def edge_429(*_args, **_kwargs):
                voice_mod._LAST_ERRORS["edge"] = "HTTP 429 rate limit"
                return "", []

            def piper_ok(_text, out_wav, _model):
                out_wav.write_bytes(b"RIFF" + b"0" * 5000)
                return True

            def convert_ok(_wav, out_mp3):
                _write_mp3(out_mp3)
                return True

            with mock.patch.object(voice_mod, "_synthesize_edge", side_effect=edge_429), \
                 mock.patch.object(voice_mod, "_synthesize_piper", side_effect=piper_ok), \
                 mock.patch.object(voice_mod, "_wav_to_mp3", side_effect=convert_ok), \
                 mock.patch.object(voice_mod, "_to_voice_ogg", return_value=False), \
                 mock.patch.object(voice_mod, "_which", side_effect=lambda name: f"/usr/bin/{name}" if name in ("piper", "ffmpeg") else None):
                artifact = synthesize("Текст для лимита edge", out, "limit1", config, use_cache=False)

            self.assertIsNotNone(artifact)
            self.assertEqual(artifact.engine, "piper")
            health = json.loads((out / "voice_health.json").read_text(encoding="utf-8"))
            self.assertGreater(health["edge"]["blocked_until"], 0)
            self.assertEqual(health["edge"]["last_kind"], "rate_limit")

            status = voice_engine_status(config)
            edge = next(item for item in status if item["engine"] == "edge")
            self.assertEqual(edge["state"], "cooldown")

    def test_edge_returns_after_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            config = self._config(tmp)
            out = config.data_dir / "audio"
            out.mkdir(parents=True, exist_ok=True)
            health_path = out / "voice_health.json"
            health_path.write_text(json.dumps({
                "edge": {"failures": 3, "blocked_until": 1.0, "last_error": "HTTP 429", "last_kind": "rate_limit"}
            }), encoding="utf-8")

            def edge_ok(_text, out_mp3, voice, rate="+0%"):
                _write_mp3(out_mp3)
                return voice, []

            with mock.patch.object(voice_mod, "_synthesize_edge", side_effect=edge_ok), \
                 mock.patch.object(voice_mod, "_to_voice_ogg", return_value=False):
                artifact = synthesize("Текст после cooldown", out, "recover1", config, use_cache=False)

            self.assertIsNotNone(artifact)
            self.assertEqual(artifact.engine, "edge")

    def test_google_429_switches_to_espeak(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            config = self._config(tmp, piper_model="")
            out = config.data_dir / "audio"

            def edge_network(*_args, **_kwargs):
                voice_mod._LAST_ERRORS["edge"] = "Connection timeout"
                return "", []

            def google_429(*_args, **_kwargs):
                voice_mod._LAST_ERRORS["google_tts"] = "HTTP 429 rate limit"
                return False

            def espeak_ok(_text, out_wav, _voice, _speed):
                out_wav.write_bytes(b"RIFF" + b"0" * 5000)
                return True

            def convert_ok(_wav, out_mp3):
                _write_mp3(out_mp3)
                return True

            def fake_which(name: str):
                return f"/usr/bin/{name}" if name in ("espeak-ng", "ffmpeg") else None

            with mock.patch.object(voice_mod, "_synthesize_edge", side_effect=edge_network), \
                 mock.patch.object(voice_mod, "_synthesize_google", side_effect=google_429), \
                 mock.patch.object(voice_mod, "_synthesize_espeak", side_effect=espeak_ok), \
                 mock.patch.object(voice_mod, "_wav_to_mp3", side_effect=convert_ok), \
                 mock.patch.object(voice_mod, "_to_voice_ogg", return_value=False), \
                 mock.patch.object(voice_mod, "_which", side_effect=fake_which):
                artifact = synthesize("Текст для google и espeak", out, "limit2", config, use_cache=False)

            self.assertIsNotNone(artifact)
            self.assertEqual(artifact.engine, "espeak")


if __name__ == "__main__":
    unittest.main()
