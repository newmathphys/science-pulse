import unittest

from science_pulse.enricher import enrich_post_longread
from science_pulse.models import Post


def make_post(**fields):
    body = (
        "Квантовый осциллятор — первая точно решаемая модель квантовой механики. "
        "Уровни энергии эквидистантны: E_n = ħω(n + 1/2), поэтому даже при абсолютном "
        "нуле остаётся нулевая энергия. Решение строится через полиномы Эрмита и "
        "собственные функции гауссова вида; это объясняет спектры молекул и "
        "теплоёмкость кристаллов при низких температурах. "
    ) * 3
    values = dict(
        id="enrich1",
        domain="physics",
        title="Квантовый осциллятор и нулевые колебания",
        hook="Почему осциллятор не замирает при абсолютном нуле?",
        body=body,
        formula_plain="x**2 + 1",
        source_name="test",
        meta={
            "era": "1925 · Гёттинген",
            "scientist": "Вернер Гейзенберг",
            "formula_vars": "ħ — постоянная Планка, ω — циклическая частота",
            "constants_used": ["hbar"],
            "prereq_ids": ["planck_quantum"],
            "unlocks_concepts": ["квантовая теория поля"],
            "modern_application": "лазеры, квантовые компьютеры, спектроскопия",
            "section_num": "5.1",
        },
    )
    values.update(fields)
    return Post(**values)


class EnricherTests(unittest.TestCase):
    def test_longread_has_five_sections(self):
        text = enrich_post_longread(make_post())
        for marker in ("I. Исторический", "II. Аналитическая", "III. Вычислительная",
                       "IV. Связи", "V. Инженерное"):
            self.assertIn(marker, text)
        self.assertGreaterEqual(len(text), 1200)

    def test_wiki_extract_is_used(self):
        def fake_http(url, timeout=3.0):
            self.assertIn("ru.wikipedia.org", url)
            return {"query": {"pages": {"1": {"extract": "Осциллятор — система, совершающая колебания."}}}}

        text = enrich_post_longread(make_post(meta={}), http_get=fake_http)
        self.assertIn("Из энциклопедии", text)
        self.assertIn("совершающая колебания", text)

    def test_offline_timeout_falls_back(self):
        def broken_http(url, timeout=3.0):
            raise TimeoutError("нет сети")

        text = enrich_post_longread(make_post(), http_get=broken_http, timeout=0.01)
        self.assertGreaterEqual(len(text), 1200)
        self.assertNotIn("Из энциклопедии", text)

    def test_cache_prevents_second_call(self):
        post = make_post()
        calls = []

        def counting_http(url, timeout=3.0):
            calls.append(url)
            return {"query": {"pages": {"1": {"extract": "текст"}}}}

        first = enrich_post_longread(post, http_get=counting_http)
        second = enrich_post_longread(post, http_get=counting_http)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
