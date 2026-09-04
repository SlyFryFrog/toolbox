"""
Copyright 2026 Marcus Gigandet

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from scripts.copyright import copyright as copyright_tool


def make_config() -> dict:
    """Return a compact valid configuration for tests."""
    return {
        "copyright": {
            "author": "Example Author",
            "default_year": "2020",
            "fix": False,
            "license": "short",
            "exclude": [r"excluded\.py$"],
        },
        "licenses": {"short": {"text": "Copyright {years} {author}\nLicense text."}},
        "languages": {
            "python": {
                "extensions": ["py"],
                "block_start": '"""',
                "block_end": '"""',
            },
            "rust": {"extensions": [".rs"], "line_prefix": "//"},
        },
    }


class CopyrightToolTests(unittest.TestCase):
    """Exercise checking, fixing, configuration, and file handling."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def enforcer(self, *, fix: bool) -> copyright_tool.CopyrightEnforcer:
        return copyright_tool.CopyrightEnforcer(
            make_config(), self.root, fix=fix, verbose=False, config_dir=self.root
        )

    def test_fix_preserves_shebang_cookie_and_crlf(self) -> None:
        source = self.root / "script.py"
        source.write_bytes(
            b"#!/usr/bin/env python3\r\n# coding: utf-8\r\nprint('ok')\r\n"
        )

        fixer = self.enforcer(fix=True)
        self.assertEqual(fixer.run(), copyright_tool.CopyrightStatus.SUCCESS)

        contents = source.read_bytes()
        self.assertTrue(
            contents.startswith(b"#!/usr/bin/env python3\r\n# coding: utf-8\r\n")
        )
        self.assertIn(b'"""\r\nCopyright 2020 Example Author', contents)
        self.assertNotIn(b"\n", contents.replace(b"\r\n", b""))
        self.assertTrue(self.enforcer(fix=False).check_file(source))

    def test_fix_replaces_stale_header_instead_of_duplicating_it(self) -> None:
        source = self.root / "main.rs"
        source.write_text(
            "// Copyright 1999 Somebody Else\n// Old license\n\nfn main() {}\n"
        )

        self.enforcer(fix=True).run()

        contents = source.read_text()
        self.assertEqual(contents.count("Copyright"), 1)
        self.assertTrue(contents.startswith("// Copyright 2020 Example Author\n"))
        self.assertNotIn("Old license", contents)

    def test_fix_mode_does_not_report_unchanged_file_as_fixed(self) -> None:
        source = self.root / "main.rs"
        source.write_text("fn main() {}\n")
        fixer = self.enforcer(fix=True)
        output = StringIO()

        with (
            mock.patch.object(fixer, "check_file", return_value=False),
            mock.patch.object(fixer, "fix_file", return_value=False),
            redirect_stdout(output),
        ):
            status = fixer.run()

        self.assertEqual(status, copyright_tool.CopyrightStatus.SUCCESS)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(fixer.violations, (source.resolve(),))

    def test_check_requires_the_configured_header(self) -> None:
        style = copyright_tool.CommentStyle(None, None, "//")
        text = "// Copyright 2020 Another Author\n\nfn main() {}\n"

        self.assertTrue(copyright_tool.has_header_at_top(text, style))
        self.assertFalse(
            copyright_tool.has_header_at_top(
                text,
                style,
                "// Copyright 2020 Example Author\n// License text.\n\n",
            )
        )

    def test_symmetric_ada_block_delimiters_occupy_complete_lines(self) -> None:
        style = copyright_tool.CommentStyle("-- ", "-- ", "-- ")
        expected = copyright_tool.format_header(
            "Copyright 2020 Example Author\n\nLicense text.", style
        )
        source = expected + "package Example is\nend Example;\n"

        self.assertTrue(copyright_tool.has_header_at_top(source, style, expected))

    def test_fix_replaces_complete_ada_header_without_duplication(self) -> None:
        source = self.root / "main.ads"
        source.write_text(
            "-- \n"
            "-- Copyright 1999 Somebody Else\n"
            "--\n"
            "-- Old license\n"
            "-- \n\n"
            "package Main is\nend Main;\n"
        )
        config = make_config()
        config["languages"]["ada"] = {
            "extensions": [".ads"],
            "block_start": "--",
            "line_prefix": "-- ",
            "block_end": "--",
        }
        fixer = copyright_tool.CopyrightEnforcer(
            config, self.root, fix=True, verbose=False, config_dir=self.root
        )

        fixer.run()
        contents = source.read_text()
        fixer.run()

        self.assertEqual(source.read_text(), contents)
        self.assertEqual(contents.count("Copyright"), 1)
        self.assertNotIn("Old license", contents)
        self.assertEqual(contents.count("package Main is"), 1)

    def test_check_mode_reports_without_modifying(self) -> None:
        source = self.root / "missing.py"
        source.write_text("print('unchanged')\n")

        checker = self.enforcer(fix=False)
        self.assertEqual(checker.run(), copyright_tool.CopyrightStatus.MISSING_HEADER)
        self.assertEqual(source.read_text(), "print('unchanged')\n")
        self.assertEqual(checker.violations, (source,))

    def test_excludes_and_extension_normalization(self) -> None:
        excluded = self.root / "excluded.py"
        excluded.write_text("print('ignored')\n")
        config = make_config()

        self.assertIsNotNone(copyright_tool.get_language(excluded, config))
        checker = copyright_tool.CopyrightEnforcer(
            config, self.root, fix=False, verbose=False
        )
        self.assertEqual(checker.run(), copyright_tool.CopyrightStatus.SUCCESS)
        self.assertEqual(checker.violations, ())

    def test_license_file_is_relative_to_config(self) -> None:
        licenses = self.root / "licenses"
        licenses.mkdir()
        (licenses / "notice.txt").write_text("Copyright {years} {author}\n")
        config = make_config()
        config["licenses"]["short"] = {"file": "licenses/notice.txt"}

        self.assertEqual(
            copyright_tool.load_license("short", config, self.root),
            "Copyright {years} {author}\n",
        )

    def test_invalid_exclude_regex_is_rejected(self) -> None:
        config = make_config()
        config["copyright"]["exclude"] = ["["]

        with self.assertRaisesRegex(ValueError, "invalid exclude pattern"):
            copyright_tool.validate_config(config)

    def test_legacy_direct_script_invocation_performs_a_check(self) -> None:
        source = self.root / "missing.py"
        source.write_text("print('unchanged')\n")
        config_path = self.root / "config.toml"
        config_path.write_text("""
[copyright]
fix = false
default_year = "2020"
author = "Example Author"
license = "short"

[licenses.short]
text = "Copyright {years} {author}"

[languages.python]
extensions = [".py"]
block_start = '\"\"\"'
block_end = '\"\"\"'
""".lstrip())
        toolbox_root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            [
                sys.executable,
                str(toolbox_root / "scripts/copyright/copyright.py"),
                "--config",
                str(config_path),
                "--directory",
                str(self.root),
                "--check",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            result.returncode, copyright_tool.CopyrightStatus.MISSING_HEADER.number
        )
        self.assertIn("VIOLATION", result.stdout)
        self.assertEqual(source.read_text(), "print('unchanged')\n")


if __name__ == "__main__":
    unittest.main()
