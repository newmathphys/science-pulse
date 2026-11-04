import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from science_pulse.config import Config
from science_pulse.edge import EdgeSync
from science_pulse.models import Post
from science_pulse.storage import Storage


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code


def make_post(pid="p1"):
    return Post(
        id=pid,
        domain="math",
        title="Тестовая теорема",
        hook="Крючок",
        body="Длинный текст с формулой $x^2$ для проверки edge-синхронизации.",
        formula_plain="x^2",
        source_name="test",
        source_url="https://example.org",
    )


ENV = {"CF_WORKER_URL": "https://worker.example", "INGEST_SECRET": "secret"}


class EdgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=self.root)
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.post = make_post()
        self.storage.add_post(self.post)
        self.storage.mark_published(self.post.id, card_file_id="F1")
        (self.config.cards_dir / f"{self.post.id}.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def _post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(200)

    def test_unavailable_without_env(self):
        sync = EdgeSync(self.config, self.storage, http_post=self._post)
        with patch.dict("os.environ", {}, clear=True):
            result = sync.sync()
        self.assertFalse(result["ok"])
        self.assertEqual(result["pushed"], 0)

    def test_push_card_and_node(self):
        with patch.dict("os.environ", ENV, clear=False):
            sync = EdgeSync(self.config, self.storage, http_post=self._post)
            result = sync.sync()
        self.assertTrue(result["ok"])
        self.assertEqual(result["pushed"], 1)
        url, kwargs = self.calls[0]
        self.assertEqual(url, "https://worker.example/api/ingest")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        meta = json.loads(kwargs["data"]["meta"])
        self.assertEqual(meta["id"], self.post.id)
        self.assertIn("pagerank", meta)
        self.assertIn("poincare_x", meta)
        self.assertIn("png", kwargs["files"])

    def test_failure_status(self):
        def bad(url, **kwargs):
            return FakeResponse(401)

        with patch.dict("os.environ", ENV, clear=False):
            sync = EdgeSync(self.config, self.storage, http_post=bad)
            result = sync.sync()
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], 1)


if __name__ == "__main__":
    unittest.main()
