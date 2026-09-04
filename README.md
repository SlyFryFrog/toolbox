# Toolbox

Toolbox packages its Python utilities as isolated command-line tools managed by
[uv](https://docs.astral.sh/uv/). Install `uv` once; `uvx` then downloads and
runs a requested Toolbox revision without a manual virtual environment.

## Copyright headers

The copyright tool recursively checks supported source files against one configured
header. It uses each file's Git history for the year or year range and can either
report differences or repair them.

### Configuration

```toml
[copyright]
fix = false
default_year = "2026"
author = "Example Organization"
license = "apache_2_0"
exclude = ["(^|/)generated/", "__init__\\.py$"]

[licenses.apache_2_0]
# Relative paths are resolved from the directory containing this TOML file.
file = "licenses/apache-2.0.txt"

[languages.cpp]
extensions = [".c", ".cpp", ".h", ".hpp"]
block_start = "/*"
line_prefix = " * "
block_end = " */"

[languages.rust]
extensions = [".rs"]
line_prefix = "//"

[languages.python]
extensions = [".py"]
block_start = '"""'
block_end = '"""'

[languages.ada]
extensions = [".adb", ".ads"]
block_start = '-- '
line_prefix = "-- "
block_end = '-- '
```

A license may use inline `text` instead of `file`. Templates can contain
`{years}` and `{author}`. Exclusions are Python regular expressions matched
against forward-slash-separated paths relative to the scan directory.

### Command line

Run the tool directly from GitHub. Replace `main` with a release tag or commit
SHA when a reproducible version is required:

```bash
uvx --from "git+https://github.com/marcusgigandet/toolbox.git@main" \
  toolbox-copyright \
  --config /path/to/project/config.toml \
  --directory /path/to/project/src \
  --check
```

From a local Toolbox checkout, use the project environment and lockfile:

```bash
uv sync --locked --dev
uv run --locked toolbox-copyright \
  --config tests/copyright/mock/config.toml \
  --directory tests/copyright/mock \
  --check
```

Use `--fix` to insert missing headers or replace stale/wrong headers. When neither
mode is supplied, `[copyright].fix` controls the behavior. `--check` is always
read-only, making it the recommended CI mode. A shebang, Python encoding cookie,
BOM, and the file's existing newline style are preserved.

Exit codes are `0` for success, `1` for header violations, `2` for a missing
license selection, `3` for a missing config file, and `4` for invalid config or
an I/O error.

### Reusable GitHub Actions workflow

```yaml
jobs:
  copyright:
    uses: marcusgigandet/toolbox/.github/workflows/verify_copyright.yml@main
    with:
      config: config.toml
      directory: src
```

The workflow performs a read-only check and, on failure, prints the patch that
`--fix` would produce.

## CMake code-quality helpers

```cmake
set(MODULES ...)
set(SOURCES ...)

include(<path-to-toolbox>/cmake/CodeQuality.cmake)

enforce_clang_format(
        TARGET ${PROJECT_NAME}
        FILES ${MODULES} ${SOURCES}
)

enforce_copyright(
        TARGET ${PROJECT_NAME}
        CONFIG_FILE "${CMAKE_CURRENT_SOURCE_DIR}/config.toml"
        SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/src"
        CHECK
)

generate_clangd_compdb(
        TARGET ${PROJECT_NAME}
        DEST_DIR "${CMAKE_CURRENT_SOURCE_DIR}"
)
```

`enforce_copyright` accepts either `CHECK` or `FIX`. If neither is supplied, it
uses the TOML configuration's `fix` setting. The CMake helper requires `uvx` on
`PATH` and runs the Toolbox package from the checkout containing
`CodeQuality.cmake`.
