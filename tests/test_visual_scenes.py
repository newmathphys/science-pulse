import unittest

from PIL import Image, ImageDraw

from science_pulse.book_film import _draw_astar_scene, _draw_insar_scene, _draw_kalman_scene


class VisualSceneTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("RGB", (640, 320), "#FAF8F4")
        self.draw = ImageDraw.Draw(self.image)
        self.box = (20, 20, 620, 300)

    def test_insar_scene_draws(self):
        _draw_insar_scene(self.draw, self.box, 1.0, 0.7)
        self.assertNotEqual(self.image.getbbox(), None)

    def test_kalman_scene_draws(self):
        _draw_kalman_scene(self.draw, self.box, 1.0, 0.7)
        self.assertNotEqual(self.image.getbbox(), None)

    def test_astar_scene_draws(self):
        _draw_astar_scene(self.draw, self.box, 1.0, 0.7)
        self.assertNotEqual(self.image.getbbox(), None)


if __name__ == "__main__":
    unittest.main()
