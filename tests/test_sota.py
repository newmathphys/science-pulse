import json
import tempfile
import time
import unittest
from pathlib import Path

from science_pulse.sota import SOTAKVExtensions
from science_pulse.storage import Storage


class SOTATests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temp.name) / "sota.db")
        self.sota = SOTAKVExtensions(self.storage)

    def tearDown(self):
        self.temp.cleanup()

    def test_thompson_returns_valid_domain(self):
        for _ in range(20):
            self.assertIn(self.sota.select_domain_thompson(), {"math", "physics", "cs"})

    def test_reward_changes_arms(self):
        self.sota.reward_domain("math", success=True)
        arms = json.loads(self.storage.kv_get("bandit_arms"))
        self.assertGreater(arms["math"]["a"], 2.0)
        self.sota.reward_domain("math", success=False)
        arms = json.loads(self.storage.kv_get("bandit_arms"))
        self.assertGreater(arms["math"]["b"], 2.0)

    def test_hawkes(self):
        self.assertTrue(self.sota.check_hawkes_ready()["ready"])
        self.sota.record_hawkes_fire()
        state = json.loads(self.storage.kv_get("hawkes_state"))
        self.assertGreater(state["last_ts"], 0)
        self.assertGreater(state["last_R"], 0)
        self.assertIn("ready", self.sota.check_hawkes_ready())

    def test_fsrs(self):
        now = time.time()
        self.assertAlmostEqual(self.sota.fsrs_retrievability(now, 7.0), 1.0, places=3)
        self.assertLess(self.sota.fsrs_retrievability(now - 30 * 86400, 7.0), 0.9)

    def test_poincare_inside_unit_disk(self):
        for index in range(1, 30):
            x, y = self.sota.poincare_xy(index, 30, "physics")
            self.assertLess((x * x + y * y) ** 0.5, 1.0)


if __name__ == "__main__":
    unittest.main()
