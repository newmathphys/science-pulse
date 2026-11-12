import tempfile
import unittest
from pathlib import Path

from science_pulse.sources.wikidata import USER_AGENT, WikidataClient


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def payload(qid="Q11518", label="Теорема Пифагора", desc="теорема евклидовой геометрии", formula="a^2+b^2=c^2"):
    return {
        "results": {
            "bindings": [
                {
                    "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
                    "itemLabel": {"value": label},
                    "itemDescription": {"value": desc},
                    "formula": {"value": formula},
                }
            ]
        }
    }


class WikidataTests(unittest.TestCase):
    def test_lookup_parses_and_caches(self):
        calls = []

        def get(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(payload())

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            client = WikidataClient(cache, http_get=get)
            first = client.lookup("Pythagorean theorem")
            second = client.lookup("Pythagorean theorem")

        self.assertEqual(first["qid"], "Q11518")
        self.assertEqual(first["term"], "Теорема Пифагора")
        self.assertIn("a^2", first["formula"])
        self.assertEqual(second, first)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["headers"]["User-Agent"], USER_AGENT)

    def test_empty_result_is_not_cached(self):
        client = WikidataClient(Path("/tmp") / "none.json", http_get=lambda *a, **k: FakeResponse({"results": {"bindings": []}}))
        self.assertEqual(client.lookup("unknown term"), {})

    def test_cached_lookup_is_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            cache.write_text('{"ring": {"qid": "Q2070", "term": "Кольцо"}}', encoding="utf-8")
            client = WikidataClient(cache, http_get=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network")))
            self.assertEqual(client.lookup("ring")["qid"], "Q2070")
            self.assertEqual(client.lookup_cached("RING")["term"], "Кольцо")


if __name__ == "__main__":
    unittest.main()
