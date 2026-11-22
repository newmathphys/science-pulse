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

    def test_hook_not_duplicated_when_prefix_of_body(self):
        """«Ключевой вопрос», совпадающий с началом тела, в лонгрид не дублируется."""
        from science_pulse.enricher import _hook_repeats_body

        body = "Буфер — область памяти для временного хранения данных."
        self.assertTrue(_hook_repeats_body(body, body + " Обмен идёт с устройствами."))
        self.assertFalse(_hook_repeats_body("Почему небо синее?", "Рассеяние Рэлея объясняет цвет."))

    def test_longread_drops_repeated_hook(self):
        hook = "Квантовый осциллятор — первая точно решаемая модель квантовой механики."
        text = enrich_post_longread(make_post(hook=hook))
        self.assertNotIn("Ключевой вопрос: Квантовый осциллятор — первая", text)

    def test_wiki_digest_cleans_headings_and_stress(self):
        from science_pulse.enricher import _wiki_digest

        out = _wiki_digest("Введе\u0301ние — текст.\n\n== История ==\n\nПодро\u0301бности.", 500)
        self.assertIn("Введение — текст.", out)
        self.assertIn("История", out)
        self.assertNotIn("==", out)

    def test_spravka_does_not_repeat_body(self):
        body = ("Буфер — область памяти для временного хранения данных при вводе "
                "или выводе для сглаживания разницы скоростей.")

        def fake_http(url, timeout=3.0):
            return {"query": {"pages": {"1": {"extract": body + " Далее идут подробности применения буферов."}}}}

        text = enrich_post_longread(make_post(body=body, meta={}), http_get=fake_http)
        self.assertEqual(text.count("Буфер — область памяти для временного хранения"), 1)

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
