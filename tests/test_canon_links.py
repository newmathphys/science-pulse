import unittest

from science_pulse.cards_academic import ARCHETYPES, SIMULATIONS
from science_pulse.config import Config
from science_pulse.constants import CONSTANTS
from science_pulse.sources.history_canon import CANON, HistoryCanonSource

INTERDISCIPLINARY = ("schrodinger", "insar_ndvi", "schwarzschild_light", "quantum_tunneling", "lj_lorenz")


class CanonLinksTests(unittest.TestCase):
    """«Тройная связь времени»: учёный+эпоха → константы → применение сегодня."""

    def setUp(self):
        self.source = HistoryCanonSource(Config(raw={}))
        self.by_id = {item["id"]: item for item in CANON}

    def test_every_node_has_triple_link(self):
        for index, item in enumerate(CANON):
            post = self.source.fetch(limit=1, cycle=index)[0]
            self.assertTrue(post.meta.get("scientist"), item["id"])
            self.assertTrue(post.meta.get("era"), item["id"])
            self.assertTrue(post.meta.get("modern_application"), item["id"])
            self.assertIn("constants_used", post.meta, item["id"])

    def test_prereq_ids_resolve(self):
        known = set(self.by_id)
        for item in CANON:
            for prereq in item.get("prereq_ids", []):
                self.assertIn(prereq, known, f"{item['id']}: нет узла {prereq}")
            if item["id"] in INTERDISCIPLINARY:
                self.assertTrue(item.get("prereq_ids"), item["id"])

    def test_constants_are_registered(self):
        symbols = {constant["symbol"] for constant in CONSTANTS}
        for item in CANON:
            for symbol in item.get("constants_used", []):
                self.assertIn(symbol, symbols, f"{item['id']}: константа {symbol} не в реестре")

    def test_visual_types_and_simulations(self):
        for item in CANON:
            visual = item.get("visual_type")
            if visual:
                self.assertIn(visual, ARCHETYPES, item["id"])
            simulation = item.get("simulation")
            if simulation:
                self.assertIn(simulation, SIMULATIONS, item["id"])

    def test_timeline_structure(self):
        item = self.by_id["schrodinger"]
        timeline = item["timeline"]
        self.assertGreaterEqual(len(timeline), 3)
        for entry in timeline:
            self.assertIn("year", entry)
            self.assertIn("label", entry)

    def test_table_structure(self):
        table = self.by_id["schwarzschild_light"]["table"]
        self.assertGreaterEqual(len(table["columns"]), 2)
        self.assertTrue(table["rows"])
        for row in table["rows"]:
            self.assertEqual(len(row), len(table["columns"]))

    def test_concepts_present_on_interdisciplinary(self):
        for node_id in INTERDISCIPLINARY:
            self.assertTrue(self.by_id[node_id].get("concept"), node_id)


if __name__ == "__main__":
    unittest.main()