import unittest

from PIL import Image, ImageDraw

from science_pulse.models import Post
from science_pulse.book_film import (
    BookFilmScene,
    _draw_astar_scene, _draw_attention_scene, _draw_diffusion_scene,
    _draw_fourier_scene, _draw_insar_scene, _draw_kalman_scene,
    _draw_markov_scene, _draw_momentum_scene, _draw_reinforce_scene,
    _draw_vectors_scene,
)


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

    def test_generic_scene_does_not_require_fr_curve(self):
        post = Post(id="generic", domain="physics", title="E = mc²",
                    body="Энергия и масса. " * 20, formula_plain="E = mc^2")
        scene = BookFilmScene(post, 640, 640)
        try:
            scene._draw_generic_scene(self.draw, self.box, 1.0, 0.7, {})
        finally:
            scene.close()
        self.assertNotEqual(self.image.getbbox(), None)

    def test_remaining_seven_scenes_draw(self):
        for drawer in (
            _draw_fourier_scene, _draw_markov_scene, _draw_attention_scene,
            _draw_diffusion_scene, _draw_vectors_scene, _draw_momentum_scene,
            _draw_reinforce_scene,
        ):
            image = Image.new("RGB", (640, 320), "#FAF8F4")
            draw = ImageDraw.Draw(image)
            drawer(draw, self.box, 1.0, 0.7)
            self.assertNotEqual(image.getbbox(), None, drawer.__name__)


if __name__ == "__main__":
    unittest.main()
