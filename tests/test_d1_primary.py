import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from science_pulse.config import Config
from science_pulse.pipeline import Pipeline
from science_pulse.storage import Storage

ENV = {"CF_WORKER_URL": "https://worker.example", "INGEST_SECRET": "secret"}


class FakeSources:
    sources = {}

    def fetch(self, limit_per_source=2, domains=None, include_offline=True):
        return []

    def status(self):
        return []


class FakePublishers:
    def __init__(self, storage):
        self.storage = storage

    def publish(self, *args, **kwargs):
        return []

    def available_platforms(self):
        return []

    def status(self):
        return []


class D1PrimaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(
            raw={"data_dir": "data", "dist_dir": "dist", "edge": {"d1_primary": True}},
            root=self.root,
        )
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.pipeline = Pipeline(self.config, self.storage, FakeSources(), FakePublishers(self.storage))

    def tearDown(self):
        self.temp.cleanup()

    def test_enabled_with_secrets(self):
        with patch.dict("os.environ", ENV, clear=False):
            self.assertTrue(self.pipeline.d1_primary_enabled())

    def test_disabled_without_secrets(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(self.pipeline.d1_primary_enabled())

    def test_disabled_by_config(self):
        self.config.raw["edge"] = {"d1_primary": False}
        with patch.dict("os.environ", ENV, clear=False):
            self.assertFalse(self.pipeline.d1_primary_enabled())

    def test_harvest_calls_pull_and_push(self):
        calls = {"pull": 0, "push": 0}

        def fake_pull(self):
            calls["pull"] += 1
            return {"ok": True, "merged": {}}

        def fake_push(self, batch_size=200):
            calls["push"] += 1
            return {"ok": True, "rows": 0}

        with patch.dict("os.environ", ENV, clear=False), patch(
            "science_pulse.state_export.StateSync.pull", fake_pull
        ), patch("science_pulse.state_export.StateSync.push", fake_push):
            self.pipeline.harvest()
        self.assertEqual(calls["pull"], 1)
        self.assertEqual(calls["push"], 1)

    def test_pull_state_soft_fallback(self):
        def boom(self):
            raise RuntimeError("network down")

        with patch.dict("os.environ", ENV, clear=False), patch(
            "science_pulse.state_export.StateSync.pull", boom
        ):
            result = self.pipeline.pull_state()
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
