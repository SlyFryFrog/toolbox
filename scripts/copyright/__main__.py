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

import argparse
import sys
from pathlib import Path

from .copyright import CopyrightEnforcer, CopyrightStatus, load_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check or repair copyright headers using Git history."
    )
    parser.add_argument("--config", default="config.toml", help="TOML configuration")
    parser.add_argument(
        "--directory", default=".", help="root directory to scan recursively"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="check without modifying files"
    )
    mode.add_argument(
        "--fix", action="store_true", help="repair missing or stale headers"
    )
    # Kept so existing workflow callers continue to force check-only behavior.
    parser.add_argument("--override", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface and return its process exit code."""
    args = _parser().parse_args(argv)
    config_path = Path(args.config).resolve()

    try:
        config = load_config(config_path)
        if config is None:
            print(f"{CopyrightStatus.NO_CONFIG}: {config_path}", file=sys.stderr)
            return CopyrightStatus.NO_CONFIG.number

        copyright_config = config.get("copyright")
        if isinstance(copyright_config, dict) and not copyright_config.get("license"):
            print(CopyrightStatus.NO_LICENSE_GIVEN, file=sys.stderr)
            return CopyrightStatus.NO_LICENSE_GIVEN.number

        configured_fix = (
            bool(copyright_config.get("fix", False))
            if isinstance(copyright_config, dict)
            else False
        )
        fix = args.fix or (configured_fix and not args.check and not args.override)
        enforcer = CopyrightEnforcer(
            config=config,
            root_dir=Path(args.directory),
            config_dir=config_path.parent,
            fix=fix,
            verbose=args.verbose,
        )
        status = enforcer.run()
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        print(f"{CopyrightStatus.INVALID_CONFIG}: {error}", file=sys.stderr)
        return CopyrightStatus.INVALID_CONFIG.number

    if args.verbose or status is not CopyrightStatus.SUCCESS:
        print(status)
    return status.number


if __name__ == "__main__":
    sys.exit(main())
