"""Ветки пользователей, форки и академические плашки на сайте."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.rituals import weekly_ab_report
from science_pulse.site import SiteBuilder
from science_pulse.storage import Storage


def make_post() -> Post:
    return Post(
        id="branch1", domain="math",
        title="Пифагор: теорема о метрике",
        hook="Почему a² + b² = c²?",
        body="В прямоугольном треугольнике квадрат гипотенузы равен сумме квадратов катетов. " * 3,
        formula_latex=r"a^2 + b^2 = c^2", formula_plain="a² + b² = c²",
        source_name="Фундамент Науки",
        meta={"section_num": "1.1", "canon_id": "pythagoras", "foundation_id": "pythagoras"},
    )


class BranchSiteTests(unittest.TestCase):
    def test_site_has_branches_forks_and_badges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=root)
            config.ensure_dirs()
            storage = Storage(config.db_path)
            post = make_post()
            post.status = "published"
            storage.add_post(post)
            SiteBuilder(config, storage).build()
            index = (config.dist_dir / "index.html").read_text(encoding="utf-8")
            page = (config.dist_dir / "post" / f"{post.id}.html").read_text(encoding="utf-8")
            self.assertIn('id="branch-panel"', index)
            self.assertIn('id="branch-data"', index)
            self.assertIn('id="master-btn"', page)
            self.assertIn('[LATEX]', page)
            self.assertIn('[PYTHON]', page)
            self.assertIn('[BIBTEX]', page)
            self.assertIn('id="sandbox-fork"', page)
            self.assertIn('#fork=', page)
            self.assertIn('syllabus.html', index)
            syllabus = (config.dist_dir / "syllabus.html").read_text(encoding="utf-8")
            self.assertIn("Бесконечный поток науки", syllabus)
            self.assertIn("135", syllabus)

    def test_weekly_ab_report_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=root)
            config.ensure_dirs()
            storage = Storage(config.db_path)
            storage.add_post(make_post())

            class Pipeline:
                pass

            pipeline = Pipeline()
            pipeline.config = config
            pipeline.storage = storage
            report = weekly_ab_report(pipeline, dry_run=True)
            self.assertTrue(report["ok"])
            self.assertIn("winner", report)


if __name__ == "__main__":
    unittest.main()
