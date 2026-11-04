import math
import unittest

from science_pulse.graph import (
    SECTOR_CENTERS,
    canon_coordinates,
    canon_edges,
    conformal_factor,
    find_geodesic_path,
    hyperbolic_distance,
    max_hyperbolic_jump,
    poincare_radius,
)
from science_pulse.sources.foundation import CANON, default_prereqs, step_of


def canon_nodes():
    return [
        dict({"id": item["id"], "domain": item["domain"], "tier": step_of(item["id"])},
             prereq_ids=default_prereqs(item["id"]))
        for item in CANON
    ]


class RadiusTests(unittest.TestCase):
    def test_radius_positive_and_monotone(self):
        radii = [poincare_radius(k) for k in range(1, 7)]
        self.assertGreater(radii[0], 0.0)
        self.assertLess(radii[0], 0.1)
        for left, right in zip(radii, radii[1:]):
            self.assertLess(left, right)
        self.assertTrue(all(value < 1.0 for value in radii))

    def test_radius_matches_spec(self):
        self.assertAlmostEqual(poincare_radius(1), math.tanh((1 - 0.82) / 2.8), places=6)
        self.assertAlmostEqual(poincare_radius(6), math.tanh((6 - 0.82) / 2.8), places=6)


class MetricTests(unittest.TestCase):
    def test_conformal_factor(self):
        self.assertAlmostEqual(conformal_factor(0.0), 4.0, places=9)
        self.assertGreater(conformal_factor(0.9), conformal_factor(0.1))

    def test_distance(self):
        self.assertAlmostEqual(hyperbolic_distance((0.1, 0.1), (0.1, 0.1)), 0.0, places=9)
        near = hyperbolic_distance((0.0, 0.0), (0.3, 0.0))
        far = hyperbolic_distance((0.0, 0.0), (0.9, 0.0))
        self.assertGreater(far, near)


class CoordinateTests(unittest.TestCase):
    def test_sector_centers(self):
        self.assertAlmostEqual(SECTOR_CENTERS["math"], math.pi / 2)
        self.assertAlmostEqual(SECTOR_CENTERS["cs"], 7 * math.pi / 6)
        self.assertAlmostEqual(SECTOR_CENTERS["physics"], 11 * math.pi / 6)

    def test_all_nodes_inside_disk(self):
        coords = canon_coordinates(canon_nodes())
        self.assertEqual(len(coords), len(CANON))
        for node_id, (x, y) in coords.items():
            self.assertLess(math.hypot(x, y), 1.0, node_id)

    def test_stage_one_nodes_do_not_collide(self):
        coords = canon_coordinates(canon_nodes())
        stage_one = [item["id"] for item in CANON if step_of(item["id"]) == 1]
        points = [coords[node_id] for node_id in stage_one]
        for index, first in enumerate(points):
            for second in points[index + 1:]:
                self.assertGreater(hyperbolic_distance(first, second), 0.05)


class GeodesicTests(unittest.TestCase):
    def test_geodesic_path_from_root(self):
        nodes = canon_nodes()
        path = find_geodesic_path(
            canon_edges(nodes), canon_coordinates(nodes),
            [item["id"] for item in CANON if step_of(item["id"]) == 1],
            "schwarzschild_light",
        )
        self.assertTrue(path)
        self.assertEqual(path[-1], "schwarzschild_light")
        self.assertEqual(len(path), len(set(path)))
        self.assertEqual(step_of(path[0]), 1)

    def test_no_path_is_empty(self):
        self.assertEqual(find_geodesic_path([], {}, ["a"], "b"), [])


class Inv8Tests(unittest.TestCase):
    def test_every_node_above_stage_one_has_parent(self):
        for item in CANON:
            if step_of(item["id"]) > 1:
                self.assertTrue(default_prereqs(item["id"]), item["id"])

    def test_jump_within_limit(self):
        nodes = canon_nodes()
        coords = canon_coordinates(nodes)
        by_id = {node["id"]: node for node in nodes}
        for item in CANON:
            tier = step_of(item["id"])
            if tier <= 1:
                continue
            for parent in default_prereqs(item["id"]):
                self.assertLess(by_id[parent]["tier"], tier)
                distance = hyperbolic_distance(coords[item["id"]], coords[parent])
                self.assertLessEqual(distance, max_hyperbolic_jump(tier) + 1e-9, item["id"])


if __name__ == "__main__":
    unittest.main()
