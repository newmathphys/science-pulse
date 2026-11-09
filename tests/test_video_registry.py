"""Реестр видео."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.video_registry import format_registry, list_videos, register_video


class VideoRegistryTests(unittest.TestCase):
    def test_register_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = Config(raw={}, root=root)
            video = root / "demo.mp4"
            video.write_bytes(b"0" * 2048)
            post = Post(id="v1", domain="cs", title="Тест", body="тело" * 40)
            entry = register_video(config, post, "explainer", "9:16", video, engine="explainer")
            self.assertEqual(entry["post_id"], "v1")
            items = list_videos(config)
            self.assertEqual(len(items), 1)
            self.assertIn("Тест", format_registry(config))


if __name__ == "__main__":
    unittest.main()
