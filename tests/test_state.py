import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from science_pulse.config import Config
from science_pulse.models import Post, PublishResult
from science_pulse.state_export import StateSync
from science_pulse.storage import Storage


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code


class FakeJsonResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload


def make_post(pid="p1"):
    filler = " ".join(f"{pid}уникальное{index}" for index in range(40))
    return Post(
        id=pid,
        domain="math",
        title=f"Разбор {pid}",
        hook="Крючок",
        body=f"{filler} формула проверки снимка состояния.",
        formula_plain="x^2",
        source_name="test",
    )


ENV = {"CF_WORKER_URL": "https://worker.example", "INGEST_SECRET": "secret"}


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=self.root)
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        post = make_post()
        self.storage.add_post(post)
        self.storage.mark_published(post.id, card_file_id="F1")
        self.storage.record_publication(
            post.id, PublishResult(platform="telegram", ok=True, external_id="1", url="https://t.me/x")
        )
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def test_snapshot_counts(self):
        snapshot = self.storage.snapshot()
        self.assertEqual(len(snapshot["posts"]), 1)
        self.assertEqual(len(snapshot["publications"]), 1)
        self.assertIn("seen", snapshot)

    def test_import_roundtrip(self):
        snapshot = self.storage.snapshot()
        other = Storage(self.root / "other.db")
        imported = other.import_rows(snapshot)
        self.assertGreaterEqual(imported, 2)
        self.assertEqual(other.count("published"), 1)

    def test_export_sql(self):
        sql = StateSync(self.config, self.storage).export_sql()
        self.assertIn("CREATE TABLE", sql)
        self.assertIn("INSERT OR REPLACE INTO posts", sql)

    def test_push(self):
        def post(url, **kwargs):
            self.calls.append((url, kwargs))
            return FakeResponse(200)

        with patch.dict("os.environ", ENV, clear=False):
            result = StateSync(self.config, self.storage, http_post=post).push()
        self.assertTrue(result["ok"])
        url, kwargs = self.calls[0]
        self.assertEqual(url, "https://worker.example/api/state")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertIn("tables", kwargs["json"])
        self.assertIn("posts", kwargs["json"]["tables"])

    def test_push_unavailable(self):
        with patch.dict("os.environ", {}, clear=True):
            result = StateSync(self.config, self.storage).push()
        self.assertFalse(result["ok"])

    def test_pull_merges_crdt(self):
        remote = {
            "posts": [
                {
                    "id": "p1",
                    "domain": "math",
                    "title": "Тестовая теорема",
                    "hook": "",
                    "body": "b",
                    "formula_latex": "",
                    "formula_plain": "",
                    "code": "",
                    "source_name": "test",
                    "source_url": "",
                    "tier": "online",
                    "quality": 0.5,
                    "status": "published",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "scheduled_for": None,
                    "published_at": "2026-02-01T00:00:00+00:00",
                    "card_path": "",
                    "card_file_id": "F9",
                    "meta_json": "{}",
                }
            ]
        }
        calls = []

        def get(url, **kwargs):
            calls.append((url, kwargs))
            return FakeJsonResponse({"ok": True, "tables": remote})

        with patch.dict("os.environ", ENV, clear=False):
            result = StateSync(self.config, self.storage, http_get=get).pull()
        self.assertTrue(result["ok"])
        self.assertEqual(calls[0][0], "https://worker.example/api/state?full=1")
        self.assertEqual(self.storage.get_post("p1").card_file_id, "F9")

    def test_push_batches(self):
        for pid in ("p2", "p3"):
            self.storage.add_post(make_post(pid))
            self.storage.mark_published(pid)
        calls = []

        def post(url, **kwargs):
            calls.append(kwargs["json"])
            return FakeResponse(200)

        with patch.dict("os.environ", ENV, clear=False):
            result = StateSync(self.config, self.storage, http_post=post).push(batch_size=2)
        self.assertTrue(result["ok"])
        post_batches = [call["tables"]["posts"] for call in calls if "posts" in call["tables"]]
        self.assertEqual(len(post_batches), 2)
        self.assertTrue(all(len(batch) <= 2 for batch in post_batches))
        self.assertGreaterEqual(result["batches"], 2)


if __name__ == "__main__":
    unittest.main()
