import unittest

from science_pulse.graph import build_links, pagerank, poincare_layout, top_by_pagerank
from science_pulse.models import Post


def make_post(pid, title, body, domain="math"):
    return Post(
        id=pid,
        domain=domain,
        title=title,
        hook="Крючок",
        body=body,
        formula_plain="x",
        source_name="test",
    )


class GraphTests(unittest.TestCase):
    def _cluster(self):
        # Три поста на одну тему (тесно связаны) и один изолированный.
        a1 = make_post("a1", "Интеграл Римана и площадь", "интеграл риман площадь предел сумма функция предел")
        a2 = make_post("a2", "Интеграл Римана в анализе", "интеграл риман площадь предел сумма функция предел")
        a3 = make_post("a3", "Определённый интеграл функции", "интеграл функция площадь предел сумма определённый")
        b1 = make_post("b1", "Сортировка слиянием", "сортировка слиянием массив рекурсия сложность", domain="cs")
        return [a1, a2, a3, b1]

    def test_build_links_by_shared_keywords(self):
        links = build_links(self._cluster())
        pairs = {(link["source"], link["target"]) for link in links}
        self.assertIn(("a1", "a2"), pairs)
        self.assertNotIn(("a1", "b1"), pairs)

    def test_pagerank_normalized_and_cluster_wins(self):
        posts = self._cluster()
        rank = pagerank([post.id for post in posts], build_links(posts))
        self.assertAlmostEqual(sum(rank.values()), 1.0, places=6)
        self.assertGreater(rank["a1"], rank["b1"])

    def test_pagerank_no_links_uniform(self):
        rank = pagerank(["x", "y", "z"], [])
        self.assertAlmostEqual(sum(rank.values()), 1.0, places=6)
        self.assertAlmostEqual(rank["x"], rank["y"], places=6)

    def test_pagerank_deterministic(self):
        posts = self._cluster()
        links = build_links(posts)
        first = pagerank([post.id for post in posts], links)
        second = pagerank([post.id for post in posts], links)
        self.assertEqual(first, second)

    def test_poincare_inside_unit_disk(self):
        posts = self._cluster()
        rank = pagerank([post.id for post in posts], build_links(posts))
        layout = poincare_layout([post.id for post in posts], {post.id: post.domain for post in posts}, rank)
        for x, y in layout.values():
            self.assertLess((x * x + y * y) ** 0.5, 1.0)

    def test_top_by_pagerank_limit(self):
        posts = self._cluster()
        rank = pagerank([post.id for post in posts], build_links(posts))
        top = top_by_pagerank([post.id for post in posts], rank, 2)
        self.assertEqual(len(top), 2)


if __name__ == "__main__":
    unittest.main()
