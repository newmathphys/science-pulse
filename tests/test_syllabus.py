import unittest

from science_pulse.config import Config
from science_pulse.sources.curriculum_crawler import (
    CATEGORY_TIERS,
    CurriculumCrawlerSource,
    RecursiveMetaCrawler,
)
from science_pulse.syllabus_tree import (
    BRANCHES,
    START_STEP,
    branches_for,
    find_topic,
    next_syllabus_topics,
    syllabus_size,
    syllabus_summary,
    syllabus_topics,
)


class SyllabusMatrixTests(unittest.TestCase):
    def test_matrix_size_and_range(self):
        summary = syllabus_summary()
        self.assertEqual(summary["branches"], 45)
        self.assertGreaterEqual(summary["topics"], 120)
        self.assertEqual(summary["first_section"], "11.1")
        self.assertEqual(summary["by_domain"], {"cs": 15, "math": 15, "physics": 15})
        self.assertGreaterEqual(syllabus_size(), 120)

    def test_sections_are_unique_and_contiguous(self):
        topics = syllabus_topics()
        sections = [topic["section_num"] for topic in topics]
        self.assertEqual(len(set(sections)), len(sections))
        self.assertEqual(sections[0], "11.1")
        last_step = START_STEP + len(BRANCHES) - 1
        self.assertEqual(sections[-1], f"{last_step}.{len(BRANCHES[-1]['topics'])}")

    def test_every_topic_is_publishable(self):
        for topic in syllabus_topics():
            self.assertTrue(topic["formula_latex"])
            self.assertTrue(topic["scientist"])
            self.assertTrue(topic["hook"].endswith("?"))
            self.assertGreaterEqual(topic["complexity_tier"], START_STEP)
            self.assertTrue(topic["branch_title"])

    def test_prereq_chain_is_causal(self):
        topics = syllabus_topics()
        self.assertTrue(topics[0]["prereq_ids"])
        for previous, current in zip(topics, topics[1:]):
            self.assertEqual(current["prereq_ids"], [previous["section_num"]])

    def test_next_window_is_deterministic_and_wraps(self):
        first = next_syllabus_topics(3, cycle=0)
        self.assertEqual([item["section_num"] for item in first], ["11.1", "11.2", "11.3"])
        self.assertEqual(next_syllabus_topics(3, cycle=0), first)
        wrapped = next_syllabus_topics(2, cycle=syllabus_size() - 1)
        self.assertEqual(wrapped[0]["section_num"], "55.3")
        self.assertEqual(wrapped[1]["section_num"], "11.1")

    def test_find_topic_and_branches(self):
        self.assertEqual(find_topic("11.2")["title"], "Бесконечность простых чисел")
        self.assertIsNone(find_topic("999.1"))
        self.assertEqual(len(branches_for("cs")), 15)
        self.assertEqual(branches_for("unknown"), [])


class CurriculumSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = CurriculumCrawlerSource(Config(raw={}))

    def test_fetch_builds_posts_with_meta(self):
        posts = self.source.fetch(limit=3, cycle=0)
        self.assertEqual(len(posts), 3)
        post = posts[0]
        self.assertEqual(post.meta["section_num"], "11.1")
        self.assertEqual(post.meta["complexity_tier"], START_STEP)
        self.assertTrue(post.formula_latex)
        self.assertEqual(post.tier, "curriculum")
        self.assertTrue(post.hook)
        self.assertTrue(post.meta["prereq_ids"])

    def test_fetch_is_deterministic(self):
        first = [post.id for post in self.source.fetch(2, 5)]
        second = [post.id for post in self.source.fetch(2, 5)]
        self.assertEqual(first, second)
        self.assertNotEqual(first, [post.id for post in self.source.fetch(2, 6)])

    def test_crawler_is_offline_without_http(self):
        self.assertEqual(self.source.discover(depth=2), [])
        self.assertEqual(self.source.crawler.subcategories("Геометрия", depth=1), [])
        self.assertEqual(self.source.crawler.category_members("Геометрия"), [])

    def test_recursive_crawler_parses_injected_payloads(self):
        def http_get(url, timeout=3.0):
            if "cmtype=subcat" in url:
                return {"query": {"categorymembers": [{"title": "Категория:Планиметрия"}]}}
            if "cmtype=page" in url:
                return {"query": {"categorymembers": [{"title": "Теорема Пифагора"}]}}
            return {"query": {"pages": {"1": {"links": [{"title": "Теорема косинусов"}]}}}}

        crawler = RecursiveMetaCrawler(http_get=http_get)
        self.assertEqual(crawler.subcategories("Геометрия", depth=2), ["Планиметрия"])
        self.assertEqual(crawler.category_members("Геометрия"), ["Теорема Пифагора"])
        self.assertEqual(crawler.article_links("Теорема Пифагора"), ["Теорема косинусов"])
        found = crawler.discover(categories=["A"], depth=1)
        self.assertTrue(found)
        self.assertTrue(all(item["origin"] == "wiki-category" for item in found))
        self.assertEqual(crawler.oeis_xref("A000045"), [])
        self.assertIn("Квантовая механика", CATEGORY_TIERS["C"])


if __name__ == "__main__":
    unittest.main()
