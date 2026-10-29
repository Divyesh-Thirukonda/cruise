"""Bundled discovery/loading boundaries; no model, network or hardware calls."""

import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modulate import skills


class RuntimeSkillTests(unittest.TestCase):
    def test_catalog_exposes_only_discovery_metadata_and_returns_fresh_values(self):
        first = skills.catalog()
        self.assertEqual(len(first), 4)
        self.assertEqual(len({entry["id"] for entry in first}), len(first))
        for entry in first:
            self.assertEqual(set(entry), {"id", "description"})
            self.assertTrue(entry["description"])
        original = first[0]["description"]
        first[0]["description"] = "caller mutation"
        self.assertEqual(skills.catalog()[0]["description"], original)

    def test_each_discovered_skill_loads_only_its_bounded_instruction_body(self):
        for entry in skills.catalog():
            with self.subTest(skill=entry["id"]):
                result = skills.load_skill(entry["id"])
                self.assertEqual(set(result), {"id", "instructions"})
                self.assertEqual(result["id"], entry["id"])
                self.assertTrue(result["instructions"].strip())
                self.assertFalse(result["instructions"].startswith("---"))
                self.assertLessEqual(len(result["instructions"].encode()), skills.MAX_SKILL_BYTES)

    def test_paths_urls_and_nonstrings_are_rejected_before_filesystem_access(self):
        with patch.object(skills, "_path") as path:
            for identifier in ("../games", "games/SKILL.md", "/etc/passwd", "GAMES", "",
                               "https://example.com/games", "games\x00", None, 1, [], {}):
                with self.subTest(identifier=identifier), self.assertRaises(skills.SkillError):
                    skills.load_skill(identifier)
            path.assert_not_called()

    def _tree(self, content):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for identifier in skills._IDS:
            path = root / identifier / "SKILL.md"
            path.parent.mkdir()
            path.write_bytes(content(identifier))
        patcher = patch.object(skills, "_ROOT", root)
        patcher.start()
        self.addCleanup(patcher.stop)
        return root

    @staticmethod
    def _document(identifier, body=b"Useful test-only instructions."):
        return f"---\nname: {identifier}\ndescription: Test-only discovery metadata.\n---\n".encode() + body

    def test_catalog_does_not_read_instruction_bodies(self):
        # An invalid UTF-8, oversize body must not be decoded/read by discovery.
        self._tree(lambda identifier: self._document(identifier, b"\xff" * (skills.MAX_SKILL_BYTES + 1)))
        self.assertEqual(len(skills.catalog()), 4)
        with self.assertRaises(skills.SkillError):
            skills.load_skill("games")

    def test_only_selected_body_is_loaded(self):
        root = self._tree(self._document)
        (root / "computer-use" / "SKILL.md").unlink()
        self.assertTrue(skills.load_skill("games")["instructions"])
        with self.assertRaises(skills.SkillError):
            skills.load_skill("computer-use")

    def test_header_and_body_limits_and_malformed_content_fail_closed(self):
        root = self._tree(self._document)
        path = root / "games" / "SKILL.md"
        invalid = (b"no frontmatter", b"---\n" + b"x" * (skills.MAX_HEADER_BYTES + 1),
                   b"---\nname: games\nname: games\ndescription: duplicate\n---\nBody",
                   self._document("computer-use"), self._document("games", b"\xff"),
                   self._document("games", b"\x00"), self._document("games", b" \n"),
                   self._document("games", b"x" * skills.MAX_SKILL_BYTES))
        for content in invalid:
            with self.subTest(content=content[:40]):
                path.write_bytes(content)
                with self.assertRaises(skills.SkillError):
                    skills.load_skill("games")

    def test_external_symlink_is_rejected_without_exposing_its_content_or_path(self):
        root = self._tree(self._document)
        with tempfile.TemporaryDirectory() as external:
            target = Path(external) / "outside.md"
            target.write_bytes(self._document("games", b"External test-only content"))
            path = root / "games" / "SKILL.md"
            path.unlink()
            path.symlink_to(target)
            with self.assertRaises(skills.SkillError) as failure:
                skills.load_skill("games")
            self.assertNotIn(external, str(failure.exception))
            self.assertNotIn("External", str(failure.exception))

    def test_directory_instead_of_skill_file_is_rejected(self):
        root = self._tree(self._document)
        path = root / "games" / "SKILL.md"
        path.unlink()
        path.mkdir()
        with self.assertRaises(skills.SkillError):
            skills.load_skill("games")

    def test_discovery_reader_stops_at_header_boundary(self):
        document = self._document("games")
        header_end = document.index(b"\n---\n", 4) + len(b"\n---\n")

        class MetadataOnly(io.BytesIO):
            def read(self, *args):
                raise AssertionError("Discovery read the body")

            def readline(self, size=-1):
                if self.tell() >= header_end:
                    raise AssertionError("Discovery read beyond metadata")
                return super().readline(size)

        with patch.object(skills, "_path", return_value=Path("test-only")), \
                patch.object(Path, "open", return_value=MetadataOnly(document)):
            result = skills._read("games", body=False)
        self.assertEqual(result["id"], "games")


if __name__ == "__main__":
    unittest.main()
