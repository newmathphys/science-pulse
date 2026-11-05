"""Источник arXiv: разбор Atom-фида, фильтры и категории (полностью без сети)."""
import unittest

from science_pulse.sources.arxiv import CATEGORY_MAP, ArxivSource
from science_pulse.sources.base import SourceError

LONG = ("Достаточно длинная аннотация научной статьи для проверки фильтра "
        "по длине: не короче ста знаков, иначе запись отсеивается. ") * 2

ATOM = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2411.00001v1</id>
    <published>2026-11-04T10:00:00Z</published>
    <title>Квантовая запутанность и границы локальных моделей</title>
    <summary>{LONG}</summary>
    <author><name>А. Иванов</name></author>
    <author><name>Б. Петров</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2411.00002v1</id>
    <title>Коротко</title>
    <summary>Мало текста.</summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2411.00003v1</id>
    <published>2026-11-03T09:00:00Z</published>
    <title>Топологическая защита краевых состояний в решётках</title>
    <summary>{LONG}</summary>
    <author><name>В. Сидоров</name></author>
  </entry>
</feed>
"""


class StubHttp:
    """Подменяет HttpClient: возвращает заранее заготовленный XML и пишет вызовы."""

    def __init__(self, text: str):
        self.text = text
        self.calls = []

    def get_text(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.text


def make_config(domains=("math", "physics")):
    return type("Cfg", (), {"domains": domains, "translate": False})()


class ArxivSourceTests(unittest.TestCase):
    def test_parses_valid_entries_and_drops_short(self):
        http = StubHttp(ATOM)
        source = ArxivSource(make_config(), http)
        posts = source.fetch(limit=2)

        self.assertEqual(len(posts), 2, "запись с коротким заголовком отсеивается")
        first = posts[0]
        self.assertEqual(first.source_name, "arXiv")
        self.assertTrue(first.source_url.startswith("http://arxiv.org/abs/"))
        self.assertTrue(first.title.startswith("Квантовая запутанность"))
        self.assertEqual(first.domain, "math")
        self.assertEqual(first.meta["published"], "2026-11-04T10:00:00Z")
        self.assertEqual(first.meta["authors"], ["А. Иванов", "Б. Петров"])
        self.assertGreaterEqual(len(first.body), 100)

    def test_cycle_selects_domain_and_category(self):
        http = StubHttp(ATOM)
        source = ArxivSource(make_config(), http)
        posts = source.fetch(limit=1, cycle=1)

        self.assertEqual(posts[0].domain, "physics")
        _, kwargs = http.calls[-1]
        self.assertEqual(kwargs["params"]["search_query"], CATEGORY_MAP["physics"])
        self.assertEqual(kwargs["params"]["sortBy"], "submittedDate")
        self.assertEqual(kwargs["params"]["start"], 0)

    def test_limit_is_respected(self):
        source = ArxivSource(make_config(), StubHttp(ATOM))
        self.assertEqual(len(source.fetch(limit=1)), 1)

    def test_empty_domains_returns_nothing_without_request(self):
        http = StubHttp(ATOM)
        source = ArxivSource(make_config(domains=()), http)
        self.assertEqual(source.fetch(limit=2), [])
        self.assertEqual(http.calls, [], "без домена сеть не дёргается")

    def test_invalid_xml_raises_source_error(self):
        source = ArxivSource(make_config(), StubHttp("<feed><entry>"))
        with self.assertRaises(SourceError):
            source.fetch(limit=1)

    def test_source_metadata(self):
        source = ArxivSource(make_config(), StubHttp(ATOM))
        self.assertEqual(source.name, "arxiv")
        self.assertEqual(source.tier, "online")
        self.assertEqual(set(source.domains), {"math", "physics", "cs"})
        self.assertTrue(source.available())


if __name__ == "__main__":
    unittest.main()
