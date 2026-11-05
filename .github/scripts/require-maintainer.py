#!/usr/bin/env python3
"""Exit 0 when the login is listed in the package's maintainers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: require-maintainer.py <name> <login>", file=sys.stderr)
        return 2
    name, login = sys.argv[1], sys.argv[2]
    entry = json.loads((ROOT / "sei" / f"{name}.json").read_text(encoding="utf-8"))
    if f"github:{login}" in (entry.get("maintainers") or []):
        return 0
    print(f"::error::{login} is not a maintainer of '{name}'")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
