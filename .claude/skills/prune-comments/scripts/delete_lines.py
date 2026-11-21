#!/usr/bin/env python3
"""Delete comment lines after checking every line still holds the expected text.

Spec (JSON):
  {"delete": {"<path>": {"<line>": "<substring>"}},
   "replace_with_pass": {"<path>": {"<line>": "<substring>"}}}

Nothing is written unless every listed line matches, so stale line numbers
cannot remove the wrong code.
"""

import json
import sys
from pathlib import Path


def main(spec_path: str) -> int:
    spec = json.loads(Path(spec_path).read_text())
    delete: dict[str, dict[str, str]] = spec.get("delete", {})
    replace: dict[str, dict[str, str]] = spec.get("replace_with_pass", {})

    files: dict[str, list[str]] = {}
    errors = []
    for path in sorted(set(delete) | set(replace)):
        lines = Path(path).read_text().split("\n")
        files[path] = lines
        for table in (delete, replace):
            for line_no, expected in table.get(path, {}).items():
                n = int(line_no)
                actual = lines[n - 1] if 0 < n <= len(lines) else "<out of range>"
                if expected not in actual:
                    errors.append(f"{path}:{n}: expected {expected!r}, found {actual!r}")
    if errors:
        print("No files changed. Mismatched lines:", *errors, sep="\n  ", file=sys.stderr)
        return 1

    removed = replaced = 0
    for path, lines in files.items():
        for line_no in replace.get(path, {}):
            line = lines[int(line_no) - 1]
            lines[int(line_no) - 1] = line[: len(line) - len(line.lstrip())] + "pass"
            replaced += 1
        for n in sorted((int(k) for k in delete.get(path, {})), reverse=True):
            del lines[n - 1]
            removed += 1
            # Drop a blank line left at the top of the file or right after a def/class line.
            if lines[n - 1 : n] == [""] and (n == 1 or lines[n - 2].rstrip().endswith(":")):
                del lines[n - 1]
        Path(path).write_text("\n".join(lines))

    print(f"Deleted {removed} line(s), replaced {replaced} with pass, in {len(files)} file(s).")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <spec.json>")
    sys.exit(main(sys.argv[1]))
