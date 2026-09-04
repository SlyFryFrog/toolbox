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

from __future__ import annotations

import datetime
import re
import runpy
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class CopyrightStatus(Enum):
    """
    Exit statuses returned by the copyright tool.
    """

    SUCCESS = (0, "OK", "No issues found")
    MISSING_HEADER = (1, "E001", "Copyright header violations found")
    NO_LICENSE_GIVEN = (2, "E002", "No license provided")
    NO_CONFIG = (3, "E003", "No configuration TOML was provided")
    INVALID_CONFIG = (4, "E004", "Invalid copyright configuration")

    def __init__(self, number: int, short_code: str, message: str):
        """
        Initialize an exit status.

        :param number Process exit code.
        :param short_code Stable machine-readable status code.
        :param message Human-readable status description.
        :return None.
        """
        self.number = number
        self.short_code = short_code
        self.message = message

    def __str__(self) -> str:
        """Format the status for command-line output."""
        return f"{self.short_code}: {self.message}"


@dataclass(frozen=True)
class CommentStyle:
    """
    Comment delimiters used to render a header.
    """

    block_start: Optional[str]
    block_end: Optional[str]
    line_prefix: Optional[str]

    @classmethod
    def from_language(cls, language: dict[str, Any]) -> "CommentStyle":
        """
        Build and validate a comment style from a language table.

        :param language Configured comment delimiters for one language.
        :return Validated comment style.
        """
        style = cls(
            language.get("block_start"),
            language.get("block_end"),
            language.get("line_prefix"),
        )
        if style.block_start and not style.block_end:
            raise ValueError("block_start requires block_end")
        if style.block_end and not style.block_start:
            raise ValueError("block_end requires block_start")
        if not style.block_start and not style.line_prefix:
            raise ValueError("a block_start or line_prefix is required")
        return style


def load_config(path: Path) -> dict[str, Any] | None:
    """
    Load a TOML configuration file.

    :param path Path to the TOML configuration file.
    :return Parsed configuration, or None when the file is absent.
    """
    if not path.is_file():
        return None
    with path.open("rb") as config_file:
        return tomllib.load(config_file)


def _validate_copyright_table(config: dict[str, Any]) -> dict[str, Any]:
    """
    Validate and return the copyright configuration table.

    :param config Complete parsed configuration.
    :return Validated copyright configuration table.
    """
    copyright_config = config.get("copyright")
    if not isinstance(copyright_config, dict):
        raise ValueError("missing [copyright] table")

    for key in ("author", "license"):
        if not isinstance(copyright_config.get(key), str) or not copyright_config[key]:
            raise ValueError(f"copyright.{key} must be a non-empty string")

    if "fix" in copyright_config and not isinstance(copyright_config["fix"], bool):
        raise ValueError("copyright.fix must be a boolean")

    default_year = str(
        copyright_config.get("default_year", datetime.datetime.now().year)
    )
    if not re.fullmatch(r"[0-9]{4}", default_year):
        raise ValueError("copyright.default_year must be a four-digit year")

    excludes = copyright_config.get("exclude", [])
    if not isinstance(excludes, list) or not all(
        isinstance(pattern, str) for pattern in excludes
    ):
        raise ValueError("copyright.exclude must be an array of regular expressions")
    for pattern in excludes:
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(f"invalid exclude pattern {pattern!r}: {error}") from error
    return copyright_config


def _validate_license(config: dict[str, Any], license_name: str) -> None:
    """
    Validate the selected license table.

    :param config Complete parsed configuration.
    :param license_name Name of the selected license.
    :return None.
    """
    licenses = config.get("licenses")
    if not isinstance(licenses, dict) or license_name not in licenses:
        raise ValueError(f"unknown license: {license_name}")
    license_config = licenses[license_name]
    has_exactly_one_source = (
        ("file" in license_config) != ("text" in license_config)
        if isinstance(license_config, dict)
        else False
    )
    if not isinstance(license_config, dict) or not has_exactly_one_source:
        raise ValueError(
            f"licenses.{license_name} must define exactly one of 'file' or 'text'"
        )
    source = license_config.get("file", license_config.get("text"))
    if not isinstance(source, str) or not source:
        raise ValueError(f"licenses.{license_name} source must be a non-empty string")


def _validate_languages(config: dict[str, Any]) -> None:
    """
    Validate all configured language tables.

    :param config Complete parsed configuration.
    :return None.
    """
    languages = config.get("languages")
    if not isinstance(languages, dict) or not languages:
        raise ValueError("at least one [languages.*] table is required")
    for name, language in languages.items():
        if not isinstance(language, dict):
            raise ValueError(f"languages.{name} must be a table")
        extensions = language.get("extensions")
        if (
            not isinstance(extensions, list)
            or not extensions
            or not all(
                isinstance(extension, str) and extension for extension in extensions
            )
        ):
            raise ValueError(f"languages.{name}.extensions must be a non-empty array")
        for delimiter in ("block_start", "block_end", "line_prefix"):
            if delimiter in language and (
                not isinstance(language[delimiter], str) or not language[delimiter]
            ):
                raise ValueError(
                    f"languages.{name}.{delimiter} must be a non-empty string"
                )
        try:
            CommentStyle.from_language(language)
        except ValueError as error:
            raise ValueError(f"invalid languages.{name}: {error}") from error


def validate_config(config: dict[str, Any]) -> None:
    """
    Validate all required configuration sections.

    :param config Complete parsed configuration.
    :return None.
    """
    copyright_config = _validate_copyright_table(config)
    _validate_license(config, copyright_config["license"])
    _validate_languages(config)


def _normalized_extension(extension: str) -> str:
    """
    Normalize a file extension to include a leading period.

    :param extension Configured file extension.
    :return Normalized extension.
    """
    return extension if extension.startswith(".") else f".{extension}"


def get_language(file: Path, config: dict[str, Any]) -> dict[str, Any] | None:
    """
    Find the configured language matching a file's extension.

    :param file Source file to classify.
    :param config Complete parsed configuration.
    :return Matching language table, or None for an unsupported extension.
    """
    for language in config.get("languages", {}).values():
        extensions = {
            _normalized_extension(extension) for extension in language["extensions"]
        }
        if file.suffix in extensions:
            return language
    return None


def load_license(
    name: str, config: dict[str, Any], base_dir: Path | None = None
) -> str:
    """
    Load a named license template from inline text or a file.

    :param name Configured license name.
    :param config Complete parsed configuration.
    :param base_dir Base directory for a relative license file path.
    :return License template text.
    """
    licenses = config.get("licenses", {})
    if name not in licenses:
        raise ValueError(f"unknown license: {name}")

    license_config = licenses[name]
    if "file" in license_config:
        license_path = Path(license_config["file"])
        if not license_path.is_absolute() and base_dir is not None:
            license_path = base_dir / license_path
        return license_path.read_text(encoding="utf-8")
    if "text" in license_config:
        return license_config["text"]
    raise ValueError(f"invalid license definition: {name}")


def format_header(text: str, style: CommentStyle) -> str:
    """
    Render license text using a language's comment delimiters.

    :param text Raw license template text.
    :param style Comment delimiters for the target language.
    :return Formatted copyright header.
    """
    lines = [line.strip() for line in text.strip().splitlines()]

    if style.block_start:
        line_prefix = style.line_prefix or ""
        body = "\n".join(
            f"{line_prefix}{line}" if line else line_prefix.rstrip() for line in lines
        )
        return f"{style.block_start}\n{body}\n{style.block_end}\n\n"

    if style.line_prefix:
        body = "\n".join(
            f"{style.line_prefix} {line}" if line else style.line_prefix
            for line in lines
        )
        return f"{body}\n\n"

    raise ValueError("invalid comment style")


_CODING_COOKIE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-_.a-zA-Z0-9]+")


def _line_end(text: str, start: int) -> int:
    """
    Find the offset immediately after the current line.

    :param text Full source text.
    :param start Offset at which the current line begins.
    :return Offset after the newline, or the text length at end of input.
    """
    newline = text.find("\n", start)
    return len(text) if newline == -1 else newline + 1


def header_offset(text: str) -> int:
    """
    Find the header insertion point after interpreter metadata.

    :param text Full source text.
    :return Offset preserving a BOM, shebang, and Python coding cookie.
    """
    offset = 1 if text.startswith("\ufeff") else 0
    first_start = offset
    first_end = _line_end(text, first_start)
    first_line = text[first_start:first_end].rstrip("\r\n")

    if first_line.startswith("#!"):
        offset = first_end
        second_end = _line_end(text, offset)
        second_line = text[offset:second_end].rstrip("\r\n")
        if _CODING_COOKIE.match(second_line):
            offset = second_end
    elif _CODING_COOKIE.match(first_line):
        offset = first_end

    return offset


def _newline_for(text: str) -> str:
    """
    Detect the newline sequence used by source text.

    :param text Full source text.
    :return CRLF when present, otherwise LF.
    """
    return "\r\n" if "\r\n" in text else "\n"


def _consume_line_breaks(text: str, offset: int, maximum: int) -> int:
    """
    Consume a bounded number of line-break sequences.

    :param text Full source text.
    :param offset Offset at which line breaks may begin.
    :param maximum Maximum number of CRLF or LF sequences to consume.
    :return Offset after the consumed line breaks.
    """
    for _ in range(maximum):
        if text.startswith("\r\n", offset):
            offset += 2
        elif text.startswith("\n", offset):
            offset += 1
        else:
            break
    return offset


def _block_header_end(text: str, start: int, style: CommentStyle) -> int | None:
    """
    Find the end of a copyright block comment.

    :param text Full source text.
    :param start Expected start offset of the header.
    :param style Block-comment delimiters for the target language.
    :return Header end offset, or None when no valid header is present.
    """
    assert style.block_start and style.block_end
    if not text.startswith(style.block_start, start):
        return None
    closing = text.find(style.block_end, start + len(style.block_start))
    if closing == -1:
        return None
    end = closing + len(style.block_end)
    if "Copyright" not in text[start:end]:
        return None
    return _consume_line_breaks(text, end, 2)


def _line_header_end(text: str, start: int, prefix: str) -> int | None:
    """
    Find the end of a contiguous copyright line-comment block.

    :param text Full source text.
    :param start Expected start offset of the header.
    :param prefix Line-comment prefix for the target language.
    :return Header end offset, or None when no valid header is present.
    """
    cursor = start
    while cursor < len(text):
        line_end = _line_end(text, cursor)
        line = text[cursor:line_end].rstrip("\r\n")
        if not line.startswith(prefix):
            break
        cursor = line_end
    if cursor == start or "Copyright" not in text[start:cursor]:
        return None
    return _consume_line_breaks(text, cursor, 1)


def _header_span(text: str, style: CommentStyle) -> tuple[int, int] | None:
    """
    Locate a copyright comment at the valid header position.

    :param text Full source text.
    :param style Comment delimiters for the target language.
    :return Header start and end offsets, or None when no header is present.
    """
    start = header_offset(text)
    if style.block_start:
        end = _block_header_end(text, start, style)
    elif style.line_prefix:
        end = _line_header_end(text, start, style.line_prefix)
    else:
        end = None
    return (start, end) if end is not None else None


def has_header_at_top(
    text: str, style: CommentStyle, expected_header: str | None = None
) -> bool:
    """
    Check for a copyright header at the valid source position.

    :param text Full source text.
    :param style Comment delimiters for the target language.
    :param expected_header Exact formatted header to require when provided.
    :return True when a matching copyright header is present.
    """
    span = _header_span(text, style)
    if span is None:
        return False
    if expected_header is None:
        return True
    start, end = span
    newline = _newline_for(text)
    return text[start:end] == expected_header.replace("\n", newline)


@dataclass(frozen=True)
class _Runtime:
    """
    Resolved settings used while scanning a source tree.
    """

    root_dir: Path
    default_year: str
    fix: bool
    verbose: bool
    exclude_patterns: tuple[re.Pattern[str], ...]
    license_text: str
    git_root: Path | None


class CopyrightEnforcer:
    """
    Validate and optionally repair configured copyright headers.
    """

    _IGNORED_DIRECTORIES = frozenset({".git", ".hg", ".svn"})

    def __init__(
        self,
        config: dict[str, Any],
        root_dir: Path,
        fix: bool,
        verbose: bool,
        config_dir: Path | None = None,
    ):
        """
        Initialize a copyright enforcer.

        :param config Complete parsed configuration.
        :param root_dir Root directory to scan recursively.
        :param fix Whether violations should be repaired.
        :param verbose Whether individual invalid files should be logged.
        :param config_dir Base directory for relative configuration paths.
        :return None.
        """
        validate_config(config)
        self._config = config
        self._violations: list[Path] = []
        resolved_root = root_dir.resolve()
        resolved_config_dir = (config_dir or Path.cwd()).resolve()
        self._runtime = _Runtime(
            root_dir=resolved_root,
            default_year=str(
                config["copyright"].get("default_year", datetime.datetime.now().year)
            ),
            fix=fix,
            verbose=verbose,
            exclude_patterns=tuple(
                re.compile(pattern)
                for pattern in config["copyright"].get("exclude", [])
            ),
            license_text=load_license(
                config["copyright"]["license"], config, resolved_config_dir
            ),
            git_root=self._find_git_root(resolved_root),
        )

    @property
    def violations(self) -> tuple[Path, ...]:
        """
        Get files with missing or stale headers from the last run.

        :return Immutable sequence of violating file paths.
        """
        return tuple(self._violations)

    @staticmethod
    def _find_git_root(root_dir: Path) -> Path | None:
        """
        Find the Git worktree containing the scan directory.

        :param root_dir Root directory to scan.
        :return Resolved Git root, or None when the directory is not in Git.
        """
        try:
            result = subprocess.run(
                ["git", "-C", str(root_dir), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None

    def _git(self, *arguments: str) -> subprocess.CompletedProcess[str] | None:
        """
        Run a non-raising Git command in the detected worktree.

        :param arguments Arguments to pass to Git.
        :return Completed process, or None when Git is unavailable.
        """
        if self._runtime.git_root is None:
            return None
        try:
            return subprocess.run(
                ["git", "-C", str(self._runtime.git_root), *arguments],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None

    def git_years(self, file: Path) -> tuple[str, str]:
        """
        Find the first and latest relevant Git years for a file.

        :param file Source file whose history should be inspected.
        :return First and latest year, falling back to the configured year.
        """
        if self._runtime.git_root is None:
            return self._runtime.default_year, self._runtime.default_year
        try:
            relative_path = (
                file.resolve().relative_to(self._runtime.git_root).as_posix()
            )
        except ValueError:
            return self._runtime.default_year, self._runtime.default_year

        history = self._git(
            "log",
            "--follow",
            "--format=%ad",
            "--date=format:%Y",
            "--",
            relative_path,
        )
        years = (
            history.stdout.splitlines() if history and history.returncode == 0 else []
        )
        if not years:
            return self._runtime.default_year, self._runtime.default_year

        start = years[-1]
        end = years[0]
        dirty = self._git(
            "status", "--porcelain", "--untracked-files=no", "--", relative_path
        )
        if dirty and dirty.stdout.strip():
            end = str(datetime.datetime.now().year)
        return start, end

    def expected_years(self, file: Path) -> str:
        """
        Format the expected copyright years for a file.

        :param file Source file whose history should be inspected.
        :return Single year or chronological year range.
        """
        start, end = self.git_years(file)
        return start if start == end else f"{start}-{end}"

    def matches_language(self, file: Path) -> bool:
        """
        Check whether a file has a configured extension.

        :param file Source file to classify.
        :return True when the file matches a configured language.
        """
        return get_language(file, self._config) is not None

    def _expected_header(self, file: Path, style: CommentStyle) -> str:
        """
        Render the exact header expected for a file.

        :param file Source file whose years should be inserted.
        :param style Comment delimiters for the target language.
        :return Fully formatted copyright header.
        """
        try:
            header_text = self._runtime.license_text.format(
                years=self.expected_years(file),
                author=self._config["copyright"]["author"],
            )
        except (KeyError, ValueError) as error:
            raise ValueError(f"invalid license template: {error}") from error
        return format_header(header_text, style)

    @staticmethod
    def _read(file: Path) -> str:
        """
        Read source text without translating newline characters.

        :param file Source file to read.
        :return Decoded source text.
        """
        with file.open("r", encoding="utf-8", newline="") as source_file:
            return source_file.read()

    @staticmethod
    def _write(file: Path, text: str) -> None:
        """
        Write source text without translating newline characters.

        :param file Source file to update.
        :param text Complete replacement source text.
        :return None.
        """
        with file.open("w", encoding="utf-8", newline="") as source_file:
            source_file.write(text)

    def check_file(self, file: Path) -> bool:
        """
        Check a supported file for its exact expected header.

        :param file Source file to check.
        :return True when the expected header is present.
        """
        language = get_language(file, self._config)
        if not language:
            return True
        style = CommentStyle.from_language(language)
        text = self._read(file)
        expected = self._expected_header(file, style)
        valid = has_header_at_top(text, style, expected)
        if self._runtime.verbose and not valid:
            print(f"INVALID {file}")
        return valid

    def fix_file(self, file: Path) -> None:
        """
        Insert or replace a supported file's copyright header.

        :param file Source file to update.
        :return None.
        """
        language = get_language(file, self._config)
        if not language:
            return
        style = CommentStyle.from_language(language)
        text = self._read(file)
        newline = _newline_for(text)
        header = self._expected_header(file, style).replace("\n", newline)
        span = _header_span(text, style)
        if span:
            start, end = span
            updated = text[:start] + header + text[end:]
        else:
            start = header_offset(text)
            updated = text[:start] + header + text[start:]
        if updated != text:
            self._write(file, updated)

    def process_file(self, file: Path) -> None:
        """
        Check one file and optionally repair it.

        :param file Source file to process.
        :return None.
        """
        if not self.matches_language(file):
            return
        if not self.check_file(file):
            self._violations.append(file)
            if self._runtime.fix:
                self.fix_file(file)

    def _is_excluded(self, file: Path) -> bool:
        """
        Check whether a source file matches an exclusion pattern.

        :param file Source file to compare with configured exclusions.
        :return True when the file should be excluded.
        """
        relative_path = file.relative_to(self._runtime.root_dir).as_posix()
        return any(
            pattern.search(relative_path) for pattern in self._runtime.exclude_patterns
        )

    def run(self) -> CopyrightStatus:
        """
        Process all supported files below the configured root.

        :return Aggregate execution status.
        """
        if not self._runtime.root_dir.is_dir():
            raise ValueError(f"directory does not exist: {self._runtime.root_dir}")

        self._violations.clear()
        files = sorted(
            (
                file
                for file in self._runtime.root_dir.rglob("*")
                if file.is_file()
                and not file.is_symlink()
                and not self._IGNORED_DIRECTORIES.intersection(
                    file.relative_to(self._runtime.root_dir).parts
                )
            ),
            key=lambda file: file.as_posix(),
        )
        for file in files:
            if not self._is_excluded(file):
                self.process_file(file)

        for index, file in enumerate(self._violations, start=1):
            action = "FIXED" if self._runtime.fix else "VIOLATION"
            print(f"[{index}/{len(self._violations)}] {action} {file}")

        if self._violations and not self._runtime.fix:
            return CopyrightStatus.MISSING_HEADER
        return CopyrightStatus.SUCCESS


if __name__ == "__main__":
    # Preserve the pre-module command used by older consumers.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    runpy.run_module("scripts.copyright", run_name="__main__")
