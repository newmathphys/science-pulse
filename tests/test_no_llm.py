"""Доказательство: контентный контур не содержит LLM."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from science_pulse.config import DEFAULT_CONFIG, Config
from science_pulse.no_llm import audit_no_llm, scan_source


class NoLlmAuditTest(unittest.TestCase):
    def test_package_has_no_llm(self):
        report = audit_no_llm()
        self.assertTrue(report["ok"], report["violations"])
        self.assertGreater(report["files"], 50)

    def test_detects_forbidden_import_and_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.py"
            path.write_text(
                "import openai\n"
                "URL = 'https://api.openai.com/v1/chat/completions'\n"
                "openai.chat.completions.create(model='x')\n",
                encoding="utf-8",
            )
            found = scan_source(path)
            self.assertTrue(any("openai" in item for item in found))
            self.assertTrue(any("api.openai.com" in item for item in found))
            self.assertTrue(any("chat.completions.create" in item for item in found))

    def test_translation_is_off_by_default(self):
        self.assertFalse(DEFAULT_CONFIG["translate"])
        self.assertFalse(Config(raw={}).translate)
        raw = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8")) or {}
        self.assertFalse(raw.get("translate", False))


if __name__ == "__main__":
    unittest.main()
