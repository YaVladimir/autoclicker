"""Malformed appearance files must not prevent startup."""

from pathlib import Path
import tempfile
import unittest

from windows_ui import load_appearance


class AppearanceTests(unittest.TestCase):
    def test_defaults_for_missing_corrupt_or_wrongly_typed_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "appearance.json"
            defaults = {"theme": "Системная", "accent": "Синий"}
            self.assertEqual(load_appearance(path), defaults)
            for content in ('{bad', '[]', '{"theme": [], "accent": {}}', '{"theme":"unknown"}'):
                path.write_text(content, encoding="utf-8")
                self.assertEqual(load_appearance(path), defaults)

    def test_valid_choices_survive_an_invalid_other_field(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "appearance.json"
            path.write_text('{"theme":"Тёмная", "accent":"unknown"}', encoding="utf-8")
            self.assertEqual(load_appearance(path), {"theme": "Тёмная", "accent": "Синий"})
