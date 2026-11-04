import unittest

from science_pulse.plotting import ExpressionError, evaluate_curve, parse_expression, plot_png


class PlottingTests(unittest.TestCase):
    def test_parse_basic(self):
        expression = parse_expression("f(x) = x^2 + 2*x + 1")
        self.assertIsNotNone(expression)

    def test_blocked_expression(self):
        with self.assertRaises(ExpressionError):
            parse_expression("__import__('os').system('echo bad')")
        with self.assertRaises(ExpressionError):
            parse_expression("lambda x: x")

    def test_evaluate_curve(self):
        curve = evaluate_curve("sin(x) * exp(-x^2/8)")
        self.assertEqual(len(curve["x"]), len(curve["re_y"]))
        self.assertIn("latex", curve)
        self.assertTrue(curve["js_fn"].startswith("(x)"))

    def test_equation_with_two_sides(self):
        curve = evaluate_curve("x^2 + y^2 = z^2")
        values = [float(value) for value in curve["re_y"]]
        self.assertGreater(max(values) - min(values), 0.5)

    def test_plot_png(self):
        data = plot_png("sin(x)")
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertGreater(len(data), 1000)


if __name__ == "__main__":
    unittest.main()
