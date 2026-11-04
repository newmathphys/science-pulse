import unittest

from science_pulse.enricher import (
    CANONICAL_ARCHIVES,
    PRIMARY_WORKS,
    build_source_lineage,
    enrich_post_longread,
    lineage_line,
)
from science_pulse.models import Post

WIKI_URL = "https://ru.wikipedia.org/wiki/Теорема_Пифагора"


def canon_post(**meta):
    payload = {
        "foundation_id": "pythagoras",
        "section_num": "1.1",
        "scientist": "Пифагор Самосский",
        "era": "530 г. до н.э. • Античная Греция",
        "modern_application": "3D-графика, GPS, L2-метрика",
        "prereq_ids": [],
        "unlocks_concepts": ["аналитическая геометрия"],
    }
    payload.update(meta)
    return Post(
        id="lin1",
        domain="math",
        title="Пифагор: теорема о метрике евклидова пространства",
        hook="Почему формула из VI века до н.э. работает в 3D-движках?",
        body="В прямоугольном треугольнике квадрат гипотенузы равен сумме квадратов катетов. " * 6,
        formula_latex="a^2 + b^2 = c^2",
        formula_plain="a² + b² = c²",
        source_name="Википедия",
        source_url=WIKI_URL,
        meta=payload,
    )


class LineageTests(unittest.TestCase):
    def test_primary_work_comes_from_canon(self):
        lineage = build_source_lineage(canon_post())
        self.assertEqual(lineage["primary_work"], PRIMARY_WORKS["pythagoras"])
        self.assertIn("Евклид", lineage["primary_work"])
        self.assertIn("DLMF", lineage["canonical_archive"])

    def test_archive_depends_on_domain_and_falls_back_to_scientist(self):
        post = canon_post()
        post.domain = "physics"
        post.meta.pop("foundation_id")
        lineage = build_source_lineage(post)
        self.assertEqual(lineage["canonical_archive"], CANONICAL_ARCHIVES["physics"])
        self.assertIn("Пифагор Самосский", lineage["primary_work"])

    def test_references_extracted_from_wiki_sections(self):
        extract = (
            "История\n\nТекст статьи.\n\n== Литература ==\n"
            "* Евклид. Начала. Книга I.\n* Мордухай-Болтовской. Комментарии к «Началам».\n\n"
            "== См. также ==\n* Теорема косинусов\n"
        )
        lineage = build_source_lineage(canon_post(), extract=extract)
        self.assertTrue(any("Евклид" in item for item in lineage["references"]))
        self.assertFalse(any("косинусов" in item for item in lineage["references"]))

    def test_references_fall_back_to_source_url(self):
        lineage = build_source_lineage(canon_post())
        self.assertEqual(lineage["references"], [WIKI_URL])

    def test_digital_source_and_human_line(self):
        lineage = build_source_lineage(canon_post())
        self.assertEqual(lineage["digital_source"]["name"], "Википедия")
        self.assertEqual(lineage["digital_source"]["url"], WIKI_URL)
        text = lineage_line(lineage)
        self.assertIn("📜 Родословная первоисточников", text)
        self.assertIn("Евклид", text)
        self.assertIn("академический свод", text)

    def test_lineage_is_cached_in_meta(self):
        post = canon_post()
        build_source_lineage(post)
        post.meta["source_lineage"] = {"primary_work": "Закэшировано"}
        self.assertEqual(build_source_lineage(post)["primary_work"], "Закэшировано")

    def test_longread_contains_lineage_and_uses_cache(self):
        post = canon_post()
        text = enrich_post_longread(post)
        self.assertIn("Родословная первоисточников", text)
        self.assertEqual(post.meta["source_lineage"]["primary_work"], PRIMARY_WORKS["pythagoras"])
        calls = []

        def broken_http(url, timeout=3.0):
            calls.append(url)
            raise AssertionError("сеть не должна вызываться при кэше")

        self.assertEqual(enrich_post_longread(post, http_get=broken_http), text)
        self.assertEqual(calls, [])

    def test_wiki_request_asks_for_full_article_and_math(self):
        seen = {}

        def http_get(url, timeout=3.0):
            seen["url"] = url
            return {"query": {"pages": {"1": {
                "extract": "Полный текст статьи. " * 60,
                "revisions": [{"slots": {"main": {"*": "текст <math>E = mc^2</math> и <math>a+b</math>"}}}],
            }}}}

        post = canon_post()
        text = enrich_post_longread(post, http_get=http_get)
        self.assertIn("extracts|revisions", seen["url"])
        self.assertNotIn("exintro", seen["url"])
        self.assertIn("Из энциклопедии", text)
        self.assertIn("$E = mc^2$", text)
        self.assertGreaterEqual(len(text), 1200)


if __name__ == "__main__":
    unittest.main()
