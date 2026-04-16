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

import argparse
import datetime
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class CopyrightStatus(Enum):
    SUCCESS = (0, "OK", "No issues found")
    MISSING_HEADER = (1, "E001", "No license header found")
    NO_LICENSE_GIVEN = (2, "E002", "No license provided")

    def __init__(self, number: int, short_code: str, message: str):
        self.number = number
        self.short_code = short_code
        self.message = message

    def __str__(self):
        return f"{self.short_code}: {self.message}"


@dataclass(frozen=True)
class CommentStyle:
    block_start: Optional[str]
    block_end: Optional[str]
    line_prefix: Optional[str]


def load_config(path: Path) -> dict:
    """
    Loads the TOML configuration file.

    :param path: Path to TOML config file.
    :return: Parsed configuration dictionary.
    """
    with open(path, "rb") as f:
        return tomllib.load(f)


def get_language(file: Path, config: dict):
    """
    Determines the language configuration for a given file based on its extension.

    :param file: File being analyzed.
    :param config: Loaded TOML configuration.
    :return: Language configuration or None if unsupported.
    """
    for lang in config["languages"].values():
        if file.suffix in lang["extensions"]:
            return lang
    return None


def load_license(name: str, config: dict) -> str:
    """
    Loads a license template from TOML configuration.

    :param name: License name from config.
    :param config: Loaded TOML configuration.
    :return: License text template.
    """
    licenses = config["licenses"]

    if name not in licenses:
        raise ValueError(f"Unknown license: {name}")

    lic = licenses[name]

    if "file" in lic:
        return Path(lic["file"]).read_text()

    if "text" in lic:
        return lic["text"]

    raise ValueError(f"Invalid license definition: {name}")


def format_header(text: str, style: CommentStyle) -> str:
    """
    Formats a license header according to the comment style of a language.

    :param text: Raw license text.
    :param style: Comment style configuration.
    :return: Formatted header string.
    """
    lines = text.strip().splitlines()

    if style.block_start:
        body = "\n".join(
            f"{style.line_prefix if style.line_prefix else ''}{line}" for line in lines
        )
        return f"{style.block_start}\n{body}\n{style.block_end}\n\n"

    if style.line_prefix:
        return "\n".join(f"{style.line_prefix} {line}" for line in lines) + "\n\n"

    raise ValueError("Invalid comment style")


def has_header_at_top(text: str, style: CommentStyle) -> bool:
    """
    Checks whether the file starts with a valid license header.

    :param text: Full contents of the file.
    :param style: Comment style configuration.
    :return: True if a license header is detected at the top, False otherwise.
    """
    stripped = text.lstrip()

    if style.block_start:
        if not stripped.startswith(style.block_start):
            return False
        if style.block_start == style.block_end:
            header = stripped.split(style.block_end, 2)[1]
        else:
            header = stripped.split(style.block_end, 1)[0]
        return "Copyright" in header

    if style.line_prefix:
        lines = stripped.splitlines()
        return any(
            line.startswith(style.line_prefix) and "Copyright" in line
            for line in lines[:10]
        )

    return False


class CopyrightEnforcer:
    YEAR_REGEX = re.compile(r"(Copyright) ([0-9]{4})(-[0-9]{4})?")

    def __init__(
        self,
        config: dict,
        root_dir: Path,
        author: str,
        default_year: str,
        license_name: str,
        fix: bool,
        verbose: bool,
    ):
        """
        Initializes the copyright enforcer.

        :param config: Loaded TOML configuration.
        :param root_dir: Root directory to scan.
        :param author: Expected author name.
        :param default_year: Default fallback year.
        :param license_name: License key from config.
        :param fix: Whether to automatically fix issues.
        :param verbose: Enable verbose output.
        """
        self.config = config
        self.root_dir = root_dir
        self.author = author
        self.default_year = default_year
        self.fix = fix
        self.verbose = verbose

        self.license_name = license_name
        self.license_text = load_license(license_name, config)

        self.violations: list[Path] = []

    def git_years(self, file: Path) -> tuple[str, str]:
        """
        Returns a year range of the git history for the file.

        :param file: File being analyzed.
        :return: Tuple containing (start_year, end_year).
        """
        try:
            start = subprocess.run(
                [
                    "git",
                    "log",
                    "--follow",
                    "--format=%cd",
                    "--date=format:%Y",
                    str(file),
                ],
                capture_output=True,
                text=True,
            ).stdout.splitlines()[-1]
        except Exception:
            start = self.default_year

        try:
            end = subprocess.run(
                ["git", "log", "-1", "--format=%cd", "--date=format:%Y", str(file)],
                capture_output=True,
                text=True,
            ).stdout.strip()
        except Exception:
            end = self.default_year

        return start or self.default_year, end or self.default_year

    def expected_years(self, file: Path) -> str:
        """
        Computes the expected copyright year string.

        :param file: File being analyzed.
        :return: Year or year range string.
        """
        start, end = self.git_years(file)
        return start if start == end else f"{start}-{end}"

    def matches_language(self, file: Path) -> bool:
        """
        Checks if a file matches configured languages.

        :param file: File being checked.
        :return: True if file should be processed.
        """
        return get_language(file, self.config) is not None

    def check_file(self, file: Path) -> bool:
        """
        Checks if the file has a valid copyright header.

        :param file: File being checked.
        :return: True if valid, False otherwise.
        """
        lang = get_language(file, self.config)
        if not lang:
            return True

        style = CommentStyle(
            lang.get("block_start"),
            lang.get("block_end"),
            lang.get("line_prefix"),
        )

        text = file.read_text(encoding="utf-8", errors="ignore")

        if not has_header_at_top(text, style):
            if self.verbose:
                print(f"LOG: No header at top of {file}")
            return False

        expected = self.expected_years(file)
        return expected in text

    def fix_file(self, file: Path) -> None:
        """
        Inserts or updates the license header for a file.

        :param file: File being fixed.
        """
        lang = get_language(file, self.config)
        if not lang:
            return

        style = CommentStyle(
            lang.get("block_start"),
            lang.get("block_end"),
            lang.get("line_prefix"),
        )

        expected_years = self.expected_years(file)

        header_text = self.license_text.format(
            years=expected_years,
            author=self.author,
        )

        header = format_header(header_text, style)

        text = file.read_text(encoding="utf-8", errors="ignore")

        if "Copyright" in text:
            text = self.YEAR_REGEX.sub(rf"\1 {expected_years}", text)
        else:
            text = header + text

        file.write_text(text, encoding="utf-8")

    def process_file(self, file: Path) -> None:
        """
        Processes a single file.

        :param file: File being processed.
        """
        if not self.matches_language(file):
            return

        if not self.check_file(file):
            self.violations.append(file)
            if self.fix:
                self.fix_file(file)

    def run(self) -> CopyrightStatus:
        """
        Processes all files in the directory.

        :return: Execution status.
        """
        for file in self.root_dir.rglob("*"):
            if file.is_file():
                self.process_file(file)

        if self.violations:
            for i, file in enumerate(self.violations):
                print(f"[{i + 1}/{len(self.violations)}] Fixing {file}")

            if not self.fix:
                return CopyrightStatus.MISSING_HEADER

        return CopyrightStatus.SUCCESS


def main() -> int:
    """
    Entry-point for the copyright script.

    :return: Exit code.
    """
    parser = argparse.ArgumentParser(description="Copyright enforcement tool")

    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--directory", default=".")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    config = load_config(Path(args.config))
    
    # Check for license
    if not config["tool"]["license"]:
        return CopyrightStatus.NO_LICENSE_GIVEN.number

    enforcer = CopyrightEnforcer(
        config=config,
        root_dir=Path(args.directory),
        author=config["tool"]["author"],
        default_year=str(datetime.datetime.now().year),
        license_name=config["tool"]["license"],
        fix=config["tool"]["fix"],
        verbose=args.verbose,
    )

    status = enforcer.run()

    if args.verbose:
        print(status)

    return status.number


if __name__ == "__main__":
    sys.exit(main())
