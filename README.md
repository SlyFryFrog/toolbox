# Toolbox

## Copyright

### Overview

Copyright is an enforcement tool for inserting copyright headers for each file in a project.

Configureable via `config.toml`:
- C / C++`
- Rust
- Python
- Ada
- etc.

### Setup

Below is an example toml for configuring language support:
```toml
[tool]
fix = true
default_year = "2026"
author = "Marcus Gigandet"
license = "apache_2_0"

[licenses.apache_2_0]
file = "licenses/apache-2.0.txt"

[languages.cpp]
extensions = [".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx", ".cppm", "ixx"]
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
line_prefix = "--"
```

### Usage

Run the tool:

```bash
python3 copyright.py --config config.toml --directory . --verbose
```

**Note**: The tool recursively fixes all files from directory.