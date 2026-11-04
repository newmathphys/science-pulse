import tempfile
import unittest
from pathlib import Path

from science_pulse.models import Post, PublishResult
from science_pulse.storage import Storage


def make_post(pid="p1"):
    return Post(
        id=pid,
        domain="math",
        title="Тестовая теорема",
        hook="Крючок",
        body="Длинный текст с формулой $x^2$ для проверки CRDT-слияния состояния.",
        formula_plain="x^2",
        source_name="test",
    )


def post_row(pid, status, **extra):
    row = {
        "id": pid,
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
        "status": status,
        "created_at": "2026-01-01T00:00:00+00:00",
        "scheduled_for": None,
        "published_at": "",
        "card_path": "",
        "card_file_id": "",
        "meta_json": "{}",
    }
    row.update(extra)
    return row


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.storage = Storage(self.root / "merge.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_post_published_beats_ready(self):
        self.storage.add_post(make_post("p1"))
        self.storage.merge_snapshot(
            {"posts": [post_row("p1", "published", card_file_id="F1", published_at="2026-02-01T00:00:00+00:00")]}
        )
        post = self.storage.get_post("p1")
        self.assertEqual(post.status, "published")
        self.assertEqual(post.card_file_id, "F1")

    def test_post_no_rollback(self):
        self.storage.add_post(make_post("p2"))
        self.storage.mark_published("p2", card_file_id="F2")
        # Старый снимок: ready, пустые поля — не должен затереть published.
        self.storage.merge_snapshot({"posts": [post_row("p2", "ready", card_file_id="", published_at="")]})
        post = self.storage.get_post("p2")
        self.assertEqual(post.status, "published")
        self.assertEqual(post.card_file_id, "F2")

    def test_publication_ok_beats_error(self):
        self.storage.add_post(make_post("p3"))
        self.storage.record_publication("p3", PublishResult(platform="vk", ok=False, error="boom"))
        self.storage.merge_snapshot(
            {
                "publications": [
                    {
                        "id": 1,
                        "post_id": "p3",
                        "platform": "vk",
                        "external_id": "9",
                        "url": "https://vk.com/wall-1_9",
                        "status": "ok",
                        "error": None,
                        "created_at": "x",
                    }
                ]
            }
        )
        rows = [row for row in self.storage.publications_for("p3") if row["platform"] == "vk"]
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[0]["external_id"], "9")

    def test_seen_union(self):
        self.storage.add_post(make_post("p4"))
        self.storage.merge_snapshot(
            {
                "seen": [
                    {
                        "hash": "deadbeef",
                        "post_id": "p4",
                        "simhash": "0x0000000000000001",
                        "title_norm": "t",
                        "body_norm": "b",
                        "created_at": "x",
                    }
                ]
            }
        )
        with self.storage.cursor() as connection:
            count = connection.execute("SELECT COUNT(*) AS c FROM seen WHERE hash = 'deadbeef'").fetchone()["c"]
        self.assertEqual(count, 1)

    def test_kv_merge(self):
        self.storage.kv_set("harvest_cursor", "5")
        self.storage.kv_set("paused", "0")
        self.storage.merge_snapshot(
            {
                "kv": [
                    {"key": "harvest_cursor", "value": "9"},
                    {"key": "paused", "value": "1"},
                    {"key": "newkey", "value": "v"},
                ]
            }
        )
        self.assertEqual(self.storage.kv_get("harvest_cursor"), "9")
        self.assertEqual(self.storage.kv_get("paused"), "0")
        self.assertEqual(self.storage.kv_get("newkey"), "v")

    def test_idempotent(self):
        self.storage.add_post(make_post("p6"))
        snapshot = {"posts": [post_row("p6", "published", card_file_id="F6")]}
        first = self.storage.merge_snapshot(snapshot)
        second = self.storage.merge_snapshot(snapshot)
        self.assertEqual(first["posts"], 1)
        self.assertEqual(second["posts"], 0)

    def test_commutative(self):
        published = post_row("p7", "published", card_file_id="FA")
        ready = post_row("p7", "ready")
        left = Storage(self.root / "left.db")
        right = Storage(self.root / "right.db")
        for store in (left, right):
            store.add_post(make_post("p7"))
        left.merge_snapshot({"posts": [published]})
        left.merge_snapshot({"posts": [ready]})
        right.merge_snapshot({"posts": [ready]})
        right.merge_snapshot({"posts": [published]})
        self.assertEqual(left.get_post("p7").status, right.get_post("p7").status)
        self.assertEqual(left.get_post("p7").card_file_id, right.get_post("p7").card_file_id)


if __name__ == "__main__":
    unittest.main()
