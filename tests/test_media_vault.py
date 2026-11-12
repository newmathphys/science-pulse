import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from science_pulse.config import Config
from science_pulse.media_vault import upload_audiogram
from science_pulse.models import Post


def make_post():
    return Post(
        id="mv1",
        domain="math",
        title="Тест",
        body="Тело поста.",
        source_name="test",
    )


class MediaVaultTests(unittest.TestCase):
    def test_without_github_token_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(raw={"data_dir": tmp}, root=Path(tmp))
            config.ensure_dirs()
            with patch.dict(os.environ, {"GITHUB_TOKEN": "", "GH_TOKEN": ""}, clear=False):
                self.assertEqual(upload_audiogram(make_post(), config), "")


if __name__ == "__main__":
    unittest.main()
