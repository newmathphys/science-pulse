"""4-уровневый календарь: слоты суток, недельные ритуалы, месячная профилактика."""

import hashlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from science_pulse import rituals
from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.storage import Storage

MSK = ZoneInfo("Europe/Moscow")


def moment(year: int, month: int, day: int, hour: int = 21) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=MSK)


def make_post(identifier: str, section: str) -> Post:
    digest = hashlib.sha1(identifier.encode()).hexdigest()
    return Post(
        id=identifier, domain="math", title=f"Параграф {section}",
        hook="Почему?", body=f"{digest} разбор для календаря и паспорта Атласа. " * 3,
        formula_latex="x^2", formula_plain="x²", source_name="Тест",
        meta={"section_num": section, "scientist": f"Учёный {digest[:4]}",
              "constants_used": [digest[:6]]},
    )


class DailySlotTests(unittest.TestCase):
    def test_slots_map_by_hour(self):
        config = Config(raw={"schedule_slots": {"09:00": "math", "13:00": "cs",
                                                "17:00": "physics", "21:00": "satellite_lab"}})
        expected = {9: "math", 12: "math", 13: "cs", 16: "cs", 17: "physics",
                    20: "physics", 21: "satellite_lab", 23: "satellite_lab"}
        for hour, domain in expected.items():
            self.assertEqual(rituals.daily_domain(moment(2026, 11, 5, hour), config), domain, hour)

    def test_default_slots_without_config(self):
        self.assertEqual(rituals.slots(None), rituals.DEFAULT_SLOTS)

    def test_satellite_slot_maps_to_physics_domain(self):
        self.assertEqual(rituals.SATELLITE_DOMAIN, "physics")


class WeeklyRitualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=Path(self.temp.name))
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.storage.connect()

    def tearDown(self):
        self.temp.cleanup()

    def test_friday_saturday_sunday(self):
        self.assertEqual(rituals.due_rituals(self.storage, self.config, moment(2026, 11, 6)), ["friday_quiz"])
        self.assertEqual(rituals.due_rituals(self.storage, self.config, moment(2026, 11, 7)), ["saturday_cheatsheet"])
        self.assertEqual(rituals.due_rituals(self.storage, self.config, moment(2026, 11, 8)), ["sunday_book"])

    def test_weekdays_have_no_rituals(self):
        for day in (2, 3, 4, 5):   # понедельник–четверг
            self.assertEqual(rituals.due_rituals(self.storage, self.config, moment(2026, 11, day)), [], day)

    def test_weekly_mark_prevents_duplicate(self):
        friday = moment(2026, 11, 6)
        self.assertIn("friday_quiz", rituals.due_rituals(self.storage, self.config, friday))
        self.storage.kv_set(rituals.KV_FRIDAY, rituals.week_key(friday))
        self.assertNotIn("friday_quiz", rituals.due_rituals(self.storage, self.config, friday))
        self.assertIn("friday_quiz", rituals.due_rituals(self.storage, self.config, moment(2026, 11, 13)))

    def test_monthly_only_on_first_day(self):
        self.assertIn("monthly_maintenance", rituals.due_rituals(self.storage, self.config, moment(2026, 12, 1)))
        self.assertEqual(rituals.due_rituals(self.storage, self.config, moment(2026, 12, 2)), [])

    def test_monthly_mark_prevents_duplicate(self):
        first = moment(2026, 12, 1)
        self.storage.kv_set(rituals.KV_MONTHLY, rituals.month_key(first))
        self.assertNotIn("monthly_maintenance", rituals.due_rituals(self.storage, self.config, first))
        self.assertIn("monthly_maintenance", rituals.due_rituals(self.storage, self.config, moment(2027, 1, 1)))


class _FakeTelegram:
    def available(self) -> bool:
        return True

    def send_poll(self, post, challenge=None, reply_to=None):
        return {"ok": True, "result": {"message_id": 1}}


class _FakePublishers:
    def __init__(self) -> None:
        self.publishers = {"telegram": _FakeTelegram()}


class _FakePipeline:
    def __init__(self, config, storage) -> None:
        self.config = config
        self.storage = storage
        self.publishers = _FakePublishers()


class RunRitualsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=Path(self.temp.name))
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.storage.connect()
        self.pipeline = _FakePipeline(self.config, self.storage)
        # Пятничной викторине нужен опубликованный пост с проверяемой задачей.
        seed = Post(
            id="quiz_seed", domain="cs", title="Алгоритм Евклида и число шагов",
            hook="Сколько шагов?", body="gcd(a, b) = gcd(b, a mod b) — пошаговый разбор алгоритма. " * 3,
            formula_latex="gcd(a, b) = gcd(b, a mod b)",
            formula_plain="gcd(a, b) = gcd(b, a mod b) • Time: O(log n)",
            source_name="Тест", meta={"section_num": "1.2"},
        )
        self.storage.add_post(seed)
        self.storage.update_post_fields(seed.id, {"status": "published"})

    def tearDown(self):
        self.temp.cleanup()

    def test_dry_run_does_not_set_marks(self):
        report = rituals.run_rituals(self.pipeline, now=moment(2026, 11, 6), dry_run=True)
        self.assertEqual(report["due"], ["friday_quiz"])
        self.assertTrue(report["results"]["friday_quiz"].get("dry_run"))
        self.assertEqual(self.storage.kv_get(rituals.KV_FRIDAY, ""), "")

    def test_run_sets_week_mark(self):
        report = rituals.run_rituals(self.pipeline, now=moment(2026, 11, 6), dry_run=False)
        self.assertTrue(report["results"]["friday_quiz"]["ok"])
        self.assertEqual(self.storage.kv_get(rituals.KV_FRIDAY, ""), rituals.week_key(moment(2026, 11, 6)))
        again = rituals.run_rituals(self.pipeline, now=moment(2026, 11, 6), dry_run=False)
        self.assertEqual(again["due"], [])

    def test_nothing_due_on_tuesday(self):
        report = rituals.run_rituals(self.pipeline, now=moment(2026, 11, 3), dry_run=True)
        self.assertEqual(report["due"], [])
        self.assertEqual(report["results"], {})


class MaintenanceTests(unittest.TestCase):
    def test_cleanup_keeps_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(raw={"data_dir": "data"}, root=Path(tmp))
            cards = Path(tmp) / "data" / "cards"
            cards.mkdir(parents=True)
            for index in range(5):
                (cards / f"c{index}.png").write_bytes(b"x")
            removed = rituals.cleanup_old_media(config, keep_last=2)
            self.assertEqual(removed, 3)
            self.assertEqual(len(list(cards.iterdir())), 2)

    def test_atlas_passport_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(raw={"data_dir": "data"}, root=Path(tmp))
            config.ensure_dirs()
            storage = Storage(config.db_path)
            storage.connect()
            for index in range(3):
                post = make_post(f"p{index}", f"1.{index}")
                storage.add_post(post)
                storage.update_post_fields(post.id, {"status": "published"})
            passport = rituals.atlas_passport(storage)
            self.assertEqual(passport["published"], 3)
            self.assertEqual(passport["sections"], 3)
            self.assertEqual(passport["scientists"], 3)

    def test_news_threshold_from_config(self):
        self.assertEqual(rituals.news_threshold(Config(raw={"trending": {"auto_publish_min_likes": 350}})), 350)
        self.assertEqual(rituals.news_threshold(Config(raw={})), 0)

    def test_threads_refresh_skipped_without_token(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"TH_ACCESS_TOKEN": ""}, clear=False):
            result = rituals.refresh_threads_token(Config(raw={}))
        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])


if __name__ == "__main__":
    unittest.main()

