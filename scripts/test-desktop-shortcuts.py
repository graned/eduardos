#!/usr/bin/env python3
"""Fast, read-only contract tests for the shipped four desktop presets."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
THEMES = ("forge-classic", "forge-neon", "forge-brutalist", "forge-eclipse")
KEYBINDINGS = (
    "bind = , PRINT, exec, edos-screenshot screen",
    "bind = $mod SHIFT, S, exec, edos-screenshot region",
    "bind = $mod SHIFT, D, exec, ghostty -e edos doctor",
)


class DesktopShortcutsTest(unittest.TestCase):
    def test_all_themes_have_same_shortcuts(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                conf = (ROOT / "themes" / theme / "hyprland.conf").read_text()
                for binding in KEYBINDINGS:
                    self.assertEqual(conf.count(binding), 1)

    def test_rust_help_matches_shipped_bindings(self):
        rust = (ROOT / "crates" / "edos" / "src" / "main.rs").read_text()
        for phrase in ("Super + Shift + S", "Super + Shift + D",
                       "Print: screen screenshot"):
            self.assertIn(phrase, rust)

    def test_screenshot_helper_is_non_persistent(self):
        nix = (ROOT / "nix" / "modules" / "desktop" / "hyprland.nix").read_text()
        for phrase in ('name = "edos-screenshot"', 'grim - | wl-copy',
                       'grim -g "$geometry" - | wl-copy',
                       'geometry="$(slurp)" || exit 0'):
            self.assertIn(phrase, nix)
        self.assertNotIn("sudo", nix)


if __name__ == "__main__":
    unittest.main()
