import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.utils.deployment import load_deployment_settings, resolve_image_wrapper


class DeploymentSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "config").mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_config(self, payload):
        path = self.root / "config" / "deployment.local.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_defaults_keep_astro_optional(self):
        settings = load_deployment_settings(project_root=self.root, environ={})

        self.assertEqual(settings.project_root, self.root.resolve())
        self.assertEqual(settings.db_path, self.root.resolve() / "data" / "hacknews.db")
        self.assertFalse(settings.astro_enabled)
        self.assertIsNone(settings.astro_blog_dir)

    def test_local_config_enables_astro_and_image_wrapper(self):
        self.write_config(
            {
                "astro": {
                    "enabled": True,
                    "repo_path": "../hacknews_recap",
                    "blog_subdir": "src/data/blog",
                },
                "image_generator": {"wrapper_path": "tools/image-wrapper.cjs"},
            }
        )

        settings = load_deployment_settings(project_root=self.root, environ={})

        self.assertTrue(settings.astro_enabled)
        self.assertEqual(
            settings.astro_blog_dir,
            (self.root / "../hacknews_recap/src/data/blog").resolve(),
        )
        self.assertEqual(
            settings.image_wrapper,
            (self.root / "tools/image-wrapper.cjs").resolve(),
        )

    def test_environment_overrides_local_config(self):
        self.write_config(
            {
                "astro": {"enabled": False, "repo_path": "ignored"},
                "image_generator": {"wrapper_path": "ignored.cjs"},
            }
        )
        env = {
            "HACKNEWS_ASTRO_ENABLED": "true",
            "HACKNEWS_ASTRO_REPO": str(self.root / "astro"),
            "HACKNEWS_IMAGE_WRAPPER": str(self.root / "wrapper.cjs"),
            "HACKNEWS_DB_PATH": str(self.root / "custom.db"),
        }

        settings = load_deployment_settings(project_root=self.root, environ=env)

        self.assertTrue(settings.astro_enabled)
        self.assertEqual(settings.astro_blog_dir, (self.root / "astro/src/data/blog").resolve())
        self.assertEqual(settings.image_wrapper, (self.root / "wrapper.cjs").resolve())
        self.assertEqual(settings.db_path, (self.root / "custom.db").resolve())

    def test_image_wrapper_falls_back_to_known_skill_locations(self):
        fake_home = self.root / "home"
        wrapper = fake_home / ".codex/skills/gpt-image-2-skill/scripts/gpt_image_2_skill.cjs"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text("", encoding="utf-8")
        settings = load_deployment_settings(project_root=self.root, environ={})

        with patch.object(Path, "home", return_value=fake_home):
            resolved = resolve_image_wrapper(settings)

        self.assertEqual(resolved, wrapper)


if __name__ == "__main__":
    unittest.main()
