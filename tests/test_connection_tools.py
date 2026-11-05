"""Инструменты подключения соцсетей: режимы подачи, `/auth` и `/sync`."""

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from science_pulse import post_modes
from science_pulse.authcheck import PLATFORMS, check_all, format_auth_table
from science_pulse.config import Config
from science_pulse.models import Post, PublishResult
from science_pulse.storage import Storage
from science_pulse.sync import format_sync_report, missing_for_platform, section_key, sync_platform

CLEAR = {name: "" for name in (
    "TG_BOT_TOKEN", "TG_CHANNEL_ID", "TH_ACCESS_TOKEN", "TH_USER_ID", "BLUESKY_HANDLE",
    "BLUESKY_APP_PASSWORD", "DISCORD_WEBHOOK_URL", "MASTODON_ACCESS_TOKEN",
    "MASTODON_INSTANCE", "VK_ACCESS_TOKEN", "VK_GROUP_ID",
)}


def make_post(identifier: str, section: str, domain: str = "math", meta=None, **fields) -> Post:
    payload = {"section_num": section}
    payload.update(meta or {})
    digest = hashlib.sha1(identifier.encode("utf-8")).hexdigest()
    body = (
        f"Разбор {identifier}: {digest[:8]} — проверка порядка летописи и синхронизации площадок. "
        f"Уникальные маркеры разбора: {digest[8:16]} {digest[16:24]} {digest[24:32]}. "
    ) * 3
    return Post(
        id=identifier, domain=domain, title=f"Параграф {section}: тема {identifier}",
        hook="Почему это работает?", body=body,
        formula_latex="x^2 + y^2 = z^2", formula_plain="x² + y² = z²",
        source_name="Тест", meta=payload, **fields,
    )


class PostModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=Path(self.temp.name))
        self.storage = Storage(self.config.db_path)
        self.storage.connect()

    def tearDown(self):
        self.temp.cleanup()

    def test_only_challenge_mode_shows_task(self):
        self.assertTrue(post_modes.shows_challenge("interactive_challenge"))
        for mode in ("pure_knowledge", "satellite_lab", "cheatsheet_save", "moku3d_film"):
            self.assertFalse(post_modes.shows_challenge(mode), mode)

    def test_declared_mode_wins(self):
        post = make_post("m1", "3.1", meta={"post_mode": "satellite_lab"})
        self.assertEqual(post_modes.mode_for_post(self.storage, self.config, post), "satellite_lab")

    def test_moku3d_theme_means_film_mode(self):
        post = make_post("m2", "3.2")
        mode = post_modes.mode_for_post(self.storage, self.config, post, theme="moku3d")
        self.assertEqual(mode, "moku3d_film")

    def test_simulation_means_satellite_lab(self):
        post = make_post("m3", "3.3", meta={"simulation": "insar"})
        self.assertEqual(post_modes.mode_for_post(self.storage, self.config, post), "satellite_lab")

    def test_challenge_every_nth_fires(self):
        self.config.raw["post_modes"] = {"challenge_every_nth": 3}
        modes = []
        for index in range(6):
            modes.append(post_modes.mode_for_post(self.storage, self.config, make_post(f"n{index}", f"4.{index}")))
        self.assertIn("interactive_challenge", modes[2::3])

    def test_pure_knowledge_dominates(self):
        modes = [post_modes.mode_for_post(self.storage, self.config, make_post(f"p{i}", f"5.{i}"))
                 for i in range(11)]
        self.assertGreaterEqual(modes.count("pure_knowledge"), 5)


class AuthCheckTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(raw={})
        self.env = mock.patch.dict(os.environ, CLEAR, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_all_platforms_without_keys(self):
        rows = check_all(self.config, http=lambda *a, **k: {"status": 200, "data": {}})
        self.assertEqual([row["platform"] for row in rows], list(PLATFORMS))
        self.assertTrue(all(row["state"] == "no_keys" for row in rows))
        table = format_auth_table(rows, html=False)
        self.assertIn("готово 0 из 6", table)
        self.assertIn("нужны TG_BOT_TOKEN", table)

    def test_telegram_ready_with_fake_http(self):
        os.environ["TG_BOT_TOKEN"] = "123:abc"
        os.environ["TG_CHANNEL_ID"] = "@channel"

        def fake(method, url, **kwargs):
            if url.endswith("/getMe"):
                return {"status": 200, "data": {"ok": True, "result": {"username": "bot", "id": 7}}}
            if url.endswith("/getChat"):
                return {"status": 200, "data": {"ok": True, "result": {"title": "Канал"}}}
            return {"status": 200, "data": {"ok": True, "result": {"status": "administrator"}}}

        rows = {row["platform"]: row for row in check_all(self.config, http=fake)}
        self.assertEqual(rows["telegram"]["state"], "ready")
        self.assertIn("права админа есть", rows["telegram"]["detail"])

    def test_broken_token_is_error(self):
        os.environ["TH_ACCESS_TOKEN"] = "bad"
        rows = {row["platform"]: row for row in check_all(
            self.config, http=lambda *a, **k: {"status": 401, "data": {"error": {"message": "invalid"}}}
        )}
        self.assertEqual(rows["threads"]["state"], "error")


class _FakePublishers:
    def __init__(self, storage):
        self.storage = storage
        self.publishers = {"threads": object(), "telegram": object()}

    def publish(self, post, card, site_url="", public_card_url="", targets=None, video=False):
        result = PublishResult(platform="threads", ok=True, external_id="42", url="https://t.me/x")
        self.storage.record_publication(post.id, result)
        return [result]


class _FakePipeline:
    def __init__(self, config, storage):
        self.config = config
        self.storage = storage
        self.publishers = _FakePublishers(storage)


class SyncPlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(
            raw={"data_dir": "data", "dist_dir": "dist", "site_base_url": "https://x.org"},
            root=self.root,
        )
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.storage.connect()
        self.pipeline = _FakePipeline(self.config, self.storage)

    def tearDown(self):
        self.temp.cleanup()

    def _publish_local(self, post: Post, platform: str = "telegram") -> None:
        self.storage.add_post(post)
        self.storage.record_publication(
            post.id, PublishResult(platform=platform, ok=True, external_id="1")
        )
        self.storage.update_post_fields(post.id, {"status": "published"})

    def test_section_order_starts_from_one(self):
        self.assertLess(section_key(make_post("a", "1.1")), section_key(make_post("b", "2.1")))
        self.assertLess(section_key(make_post("c", "9.9")), section_key(make_post("d", "10.1")))

    def test_missing_lists_published_without_target(self):
        self._publish_local(make_post("s1", "1.1"))
        self._publish_local(make_post("s2", "1.2"))
        self._publish_local(make_post("s3", "2.1"))
        self.storage.add_post(make_post("ready1", "3.1"))  # ещё не опубликован
        rows = missing_for_platform(self.storage, "threads", limit=10)
        self.assertEqual([(p.meta or {}).get("section_num") for p in rows], ["1.1", "1.2", "2.1"])

    def test_sync_publishes_in_order_and_marks_publications(self):
        self._publish_local(make_post("t1", "1.1"))
        self._publish_local(make_post("t2", "1.2"))
        result = sync_platform(self.pipeline, "threads", limit=2)
        self.assertTrue(result["ok"])
        self.assertEqual([item["section"] for item in result["published"]], ["1.1", "1.2"])
        self.assertTrue(self.storage.publication_exists("t1", "threads"))
        self.assertTrue(self.storage.publication_exists("t2", "threads"))
        again = sync_platform(self.pipeline, "threads", limit=2)
        self.assertEqual(again["missing"], 0)

    def test_sync_dry_run_publishes_nothing(self):
        self._publish_local(make_post("d1", "1.1"))
        result = sync_platform(self.pipeline, "threads", limit=1, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertFalse(self.storage.publication_exists("d1", "threads"))
        self.assertIn("Режим проверки", format_sync_report(result, html=False))

    def test_sync_unknown_platform_reports_error(self):
        result = sync_platform(self.pipeline, "unknown", limit=1)
        self.assertFalse(result["ok"])
        self.assertIn("не включена", result["error"])


if __name__ == "__main__":
    unittest.main()

