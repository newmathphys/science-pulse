"""Проверка релиза: Threads и Cloudflare без публикаций."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from science_pulse.config import Config
from science_pulse.release_check import (
    CF_MARKER,
    check_cloudflare,
    check_threads,
    format_release,
    release_status,
)


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={}, root=self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_threads_without_keys(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = check_threads(self.config)
        self.assertEqual(result["state"], "no_keys")
        self.assertEqual(result["image_mode"], "text")
        self.assertTrue(result["steps"])

    def test_threads_ready(self):
        def fake_http(method, url, **kwargs):
            return {"status": 200, "data": {"id": "42", "username": "science"}}

        with mock.patch.dict(os.environ, {"TH_USER_ID": "42", "TH_ACCESS_TOKEN": "token"}, clear=True):
            result = check_threads(self.config, http=fake_http)
        self.assertEqual(result["state"], "ready")
        self.assertIn("science", result["detail"])

    def test_cloudflare_without_url(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = check_cloudflare(self.config)
        self.assertEqual(result["state"], "no_url")
        self.assertFalse(result["secret"])
        self.assertTrue(result["steps"])

    def test_cloudflare_ready(self):
        class Response:
            status_code = 200
            text = CF_MARKER

        with mock.patch.dict(os.environ, {
            "CF_WORKER_URL": "https://worker.example",
            "INGEST_SECRET": "secret",
        }, clear=True):
            result = check_cloudflare(self.config, http_get=lambda *_a, **_k: Response())
        self.assertEqual(result["state"], "ready")
        self.assertTrue(result["secret"])

    def test_format_release_contains_next_steps(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            report = release_status(self.config)
            text = format_release(report)
        self.assertIn("Threads", text)
        self.assertIn("Cloudflare", text)
        self.assertIn("Дальше", text)


if __name__ == "__main__":
    unittest.main()
