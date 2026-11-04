import unittest
from datetime import datetime

from science_pulse.scheduler import next_run, parse_schedule, run_daemon


class FakePipeline:
    def __init__(self):
        self.calls = 0

    def run(self, dry_run=False):
        self.calls += 1
        return {"ok": True}


class SchedulerTests(unittest.TestCase):
    def test_parse_schedule(self):
        self.assertEqual(parse_schedule(["18:00", "09:00", "bad"]), [(9, 0), (18, 0)])

    def test_next_run_same_day(self):
        now = datetime(2026, 11, 1, 8, 0)
        target = next_run(now, [(9, 0), (18, 0)])
        self.assertEqual(target, datetime(2026, 11, 1, 9, 0))

    def test_next_run_next_day(self):
        now = datetime(2026, 11, 1, 19, 0)
        target = next_run(now, [(9, 0), (18, 0)])
        self.assertEqual(target, datetime(2026, 11, 2, 9, 0))

    def test_once(self):
        pipeline = FakePipeline()

        class Config:
            schedule = ["09:00", "18:00"]
            timezone = "Europe/Moscow"

        runs = run_daemon(pipeline, Config(), once=True)
        self.assertEqual(runs, 1)
        self.assertEqual(pipeline.calls, 1)


if __name__ == "__main__":
    unittest.main()
