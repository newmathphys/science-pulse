import tempfile
import unittest
from pathlib import Path

from science_pulse.models import Post, PublishResult
from science_pulse.storage import Storage, _parse_simhash


def make_post(identifier="p1", domain="math", title="Тестовая теорема"):
    return Post(
        id=identifier,
        domain=domain,
        title=title,
        hook="Крючок",
        body="Достаточно длинный текст с формулой $x^2 + y^2 = z^2$ для проверки.",
        formula_latex="x^2 + y^2 = z^2",
        formula_plain="x^2 + y^2 = z^2",
        source_name="test",
        source_url="https://example.org",
    )


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temp.name) / "test.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_add_and_dedup_by_id_and_fingerprint(self):
        post = make_post()
        self.assertTrue(self.storage.add_post(post))
        self.assertFalse(self.storage.add_post(post))
        clone = make_post("p2")
        self.assertFalse(self.storage.add_post(clone))
        self.assertEqual(self.storage.count(), 1)

    def test_near_duplicate_by_simhash(self):
        first = make_post("p1")
        self.assertTrue(self.storage.add_post(first))
        near = Post(
            id="p2",
            domain="math",
            title="Тестовая теорема (почти копия)",
            hook="Крючок",
            body="Достаточно длинный текст с формулой $x^2 + y^2 = z^2$ для проверки дубля.",
            formula_latex="x^2 + y^2 = z^2",
            formula_plain="x^2 + y^2 = z^2",
            source_name="test",
        )
        self.assertFalse(self.storage.add_post(near))

    def test_queue_and_publish(self):
        post = make_post()
        self.storage.add_post(post)
        self.assertEqual(self.storage.count("ready"), 1)
        self.assertEqual(self.storage.next_ready("math").id, post.id)
        self.storage.mark_publishing(post.id)
        self.assertEqual(self.storage.count("ready"), 0)
        self.storage.mark_published(post.id, card_path="/tmp/card.png", card_file_id="file")
        self.assertEqual(self.storage.count("published"), 1)
        self.assertEqual(self.storage.last_published().id, post.id)

    def test_publication_idempotent(self):
        post = make_post()
        self.storage.add_post(post)
        result = PublishResult(platform="telegram", ok=True, external_id="1", url="https://t.me/x")
        self.storage.record_publication(post.id, result)
        self.assertTrue(self.storage.publication_exists(post.id, "telegram"))
        self.storage.record_publication(post.id, result)
        rows = self.storage.publications_for(post.id)
        self.assertEqual(len(rows), 1)

    def test_forget_publication_allows_republish(self):
        post = make_post()
        self.storage.add_post(post)
        result = PublishResult(platform="telegram", ok=True, external_id="1", url="https://t.me/x")
        self.storage.record_publication(post.id, result)
        self.assertTrue(self.storage.publication_exists(post.id, "telegram"))
        self.assertTrue(self.storage.forget_publication(post.id, "telegram"))
        self.assertFalse(self.storage.publication_exists(post.id, "telegram"))
        self.assertFalse(self.storage.forget_publication(post.id, "telegram"))

    def test_source_circuit_breaker(self):
        self.assertFalse(self.storage.source_is_open("oeis"))
        for _ in range(3):
            self.storage.record_source_failure("oeis", "boom", failures_limit=3, open_minutes=10)
        self.assertTrue(self.storage.source_is_open("oeis"))
        self.storage.record_source_ok("oeis")
        self.assertFalse(self.storage.source_is_open("oeis"))

    def test_simhash_hex_no_overflow(self):
        self.assertEqual(_parse_simhash("0xffffffffffffffff"), 2**64 - 1)
        self.assertEqual(_parse_simhash("18446744073709551615"), 2**64 - 1)

    def test_high_bit_simhash_insert(self):
        from unittest.mock import patch

        with patch("science_pulse.storage.simhash64", return_value=2**64 - 1):
            self.assertTrue(self.storage.add_post(make_post("high")))
        with self.storage.cursor() as connection:
            row = connection.execute(
                "SELECT simhash FROM seen WHERE post_id = ?", ("high",)
            ).fetchone()
        self.assertEqual(_parse_simhash(row["simhash"]), 2**64 - 1)

    def test_checkpoint_truncates_wal(self):
        self.storage.add_post(make_post())
        self.storage.checkpoint()
        wal = Path(str(self.storage.path) + "-wal")
        if wal.exists():
            self.assertEqual(wal.stat().st_size, 0)

    def test_kv_counter(self):
        self.assertEqual(self.storage.kv_int("cycle", 0), 0)
        self.assertEqual(self.storage.bump_counter("cycle"), 1)
        self.assertEqual(self.storage.bump_counter("cycle"), 2)

    def test_set_post_meta(self):
        post = make_post()
        self.storage.add_post(post)
        self.storage.set_post_meta(post.id, "style_variant", "compact")
        self.assertEqual(self.storage.get_post(post.id).meta.get("style_variant"), "compact")

    def test_reset(self):
        self.storage.add_post(make_post())
        self.storage.kv_set("paused", "1")
        self.storage.reset()
        self.assertEqual(self.storage.count(), 0)
        self.assertEqual(self.storage.kv_get("paused", "0"), "0")


if __name__ == "__main__":
    unittest.main()
