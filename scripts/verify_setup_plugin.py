#!/usr/bin/env python3
"""Check download/source parity and exercise installation without touching a real home."""
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
import tempfile
import unittest
import zipfile

from package_setup_plugin import SOURCE, artifacts, load_installer


class PluginPackageTests(unittest.TestCase):
    def test_downloads_match_source_and_contain_only_reviewed_files(self):
        generated = artifacts()
        for path, expected in generated.items():
            self.assertEqual(path.read_bytes(), expected, f"Regenerate {path.name}")
        installer = load_installer()
        version, files = installer.package_files(SOURCE)
        self.assertEqual(version, "0.1.1")
        zipped = next(content for path, content in generated.items() if path.suffix == ".zip")
        with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
            self.assertEqual(set(archive.namelist()), {"modulate-setup/" + name for name in files})
            for info in archive.infolist():
                self.assertFalse(PurePosixPath(info.filename).is_absolute())
                self.assertNotIn("..", PurePosixPath(info.filename).parts)
                self.assertFalse(info.filename.endswith((".env", ".pem", ".key")))
                text = archive.read(info).decode()
                self.assertNotRegex(text, r"/Users/|LLM_\d{8,}|AQ\.[A-Za-z0-9_-]{20,}|sk[-_][A-Za-z0-9_-]{24,}|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY")
                self.assertEqual(archive.read(info), files[info.filename.removeprefix("modulate-setup/")])

    def test_preview_is_read_only_and_install_preserves_other_plugins(self):
        installer = load_installer()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            catalog = home / ".agents/plugins/marketplace.json"
            catalog.parent.mkdir(parents=True)
            original = {"name": "my-plugins", "custom": True, "plugins": [{"name": "keep-me", "source": "./keep"}]}
            catalog.write_text(json.dumps(original))
            before = catalog.read_bytes()
            plan = installer.install(SOURCE, home)
            self.assertFalse(Path(plan["plugin"]).exists())
            self.assertEqual(catalog.read_bytes(), before)
            result = installer.install(SOURCE, home, apply=True)
            after = json.loads(catalog.read_text())
            self.assertTrue(after["custom"])
            self.assertEqual(after["plugins"][0], original["plugins"][0])
            self.assertEqual(after["name"], "my-plugins")
            self.assertEqual(Path(result["catalog_backup"]).read_bytes(), before)
            self.assertEqual(after["plugins"][-1]["policy"]["installation"], "AVAILABLE")
            stable = catalog.read_bytes()
            installer.install(SOURCE, home, apply=True)
            self.assertEqual(catalog.read_bytes(), stable)
            self.assertFalse((home / ".codex/config.toml").exists())

    def test_conflicting_files_and_catalog_entries_are_not_overwritten(self):
        installer = load_installer()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = installer.install(SOURCE, home, apply=True)
            target = Path(result["plugin"])
            catalog = Path(result["catalog"])
            (target / "user-note.txt").write_text("keep")
            before = catalog.read_bytes()
            with self.assertRaises(ValueError):
                installer.install(SOURCE, home, apply=True)
            self.assertEqual((target / "user-note.txt").read_text(), "keep")
            self.assertEqual(catalog.read_bytes(), before)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            catalog = home / ".agents/plugins/marketplace.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({"name": "mine", "plugins": [{"name": "modulate-setup", "source": "./other"}]}))
            before = catalog.read_bytes()
            with self.assertRaises(ValueError):
                installer.install(SOURCE, home, apply=True)
            self.assertEqual(catalog.read_bytes(), before)
            self.assertFalse((home / ".codex/plugins/modulate-setup").exists())

    def test_escape_symlink_is_rejected(self):
        installer = load_installer()
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            home = Path(directory)
            (home / ".codex").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                installer.install(SOURCE, home, apply=True)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_concurrent_installs_keep_one_catalog_entry(self):
        installer = load_installer()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(installer.install, SOURCE, home, apply=True) for _ in range(2)]
                for future in futures:
                    future.result()
            catalog = json.loads((home / ".agents/plugins/marketplace.json").read_text())
            self.assertEqual([p["name"] for p in catalog["plugins"]], ["modulate-setup"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
