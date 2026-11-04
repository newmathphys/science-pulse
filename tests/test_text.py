import unittest

from science_pulse.text import (
    clean_latex_for_telegram,
    fingerprint,
    formula_to_unicode,
    hamming,
    lead_sentence,
    mask_protected,
    simhash64,
    smart_sentence_truncate,
    split_text,
    unmask_protected,
)


class TextTests(unittest.TestCase):
    def test_mask_preserves_latex_and_code(self):
        source = "Текст $E=mc^2$ и код `print(1)` и блок ```py\nx=1\n```."
        masked, saved = mask_protected(source)
        self.assertNotIn("E=mc^2", masked)
        self.assertIn("ZZZP", masked)
        restored = unmask_protected(masked, saved)
        self.assertEqual(restored, source)

    def test_split_respects_limit_and_formula(self):
        text = ("Первое предложение с формулой $a^2+b^2=c^2$. " * 40).strip()
        chunks = split_text(text, 200)
        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 200 for chunk in chunks))
        self.assertEqual("".join(chunks).replace(" ", ""), text.replace(" ", ""))

    def test_split_short_text(self):
        self.assertEqual(split_text("короткий текст", 100), ["короткий текст"])

    def test_simhash_near_duplicate(self):
        a = "Квантовый осциллятор и полином Эрмита описывает нулевые колебания вакуума"
        b = "Квантовый осциллятор и полином Эрмита описывает нулевые колебания вакуума!"
        c = "Совершенно другой текст про теорию графов, алгоритмы и сложность"
        self.assertLessEqual(hamming(simhash64(a), simhash64(b)), 4)
        self.assertGreater(hamming(simhash64(a), simhash64(c)), 6)

    def test_fingerprint_stable(self):
        class Item:
            title = "Теорема"
            body = "Одинаковый текст"
            formula_plain = "x=1"

        self.assertEqual(fingerprint(Item()), fingerprint(Item()))

    def test_formula_unicode(self):
        result = formula_to_unicode(r"\frac{a}{b} = \sqrt{x^2 + \pi}")
        self.assertIn("π", result)
        self.assertIn("√", result)
        self.assertIn("/", result)

    def test_formula_unicode_nested_frac(self):
        result = formula_to_unicode(r"$\frac{\textrm{d}y}{\textrm{d}x}$")
        self.assertEqual(result, "(dy)/(dx)")

    def test_clean_latex_for_telegram(self):
        result = clean_latex_for_telegram(r"$E_n=\hbar\omega$, $\mathbb{R}$, $\mathcal{O}(n \log n)$, $10^{-6}\:\rm s$")
        self.assertIn("Eₙ", result)
        self.assertIn("ℏ", result)
        self.assertIn("ℝ", result)
        self.assertIn("O(n log n)", result)
        self.assertIn("10⁻⁶ s", result)
        self.assertNotIn("$", result)
        self.assertNotIn("\\", result)

    def test_smart_truncate_keeps_sentence(self):
        text = "Первое предложение. Второе предложение с формулой $x^2$. Третье предложение."
        result = smart_sentence_truncate(text, 20, 40)
        self.assertTrue(result.endswith(".") or result.endswith("…"))
        self.assertNotIn("$", result)

    def test_lead_sentence(self):
        body = "Что в этом такого? Когда квантовая механика была открыта, физики получили новый язык описания мира."
        self.assertTrue(lead_sentence(body, 120).startswith("Когда квантовая"))


if __name__ == "__main__":
    unittest.main()
