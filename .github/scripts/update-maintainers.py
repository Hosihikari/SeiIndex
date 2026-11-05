#!/usr/bin/env python3
"""Add or remove a maintainer of a registered package (ADR-0033).

Only a current maintainer may ask; removing the last one needs an index
maintainer's approval. The change lands in the mirror and therefore survives
every refresh.

Usage: update-maintainers.py <name> <add|remove> <login>
Env: SENDER (issue author) and APPROVED (any non-empty value when an index
maintainer approved a last-maintainer removal).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEI_DIR = ROOT / "sei"
MAX = 20


class ChangeError(Exception):
    pass


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: update-maintainers.py <name> <add|remove> <login>", file=sys.stderr)
        return 2
    name, action, login = sys.argv[1], sys.argv[2], sys.argv[3].lstrip("@")
    if action not in ("add", "remove"):
        raise ChangeError("action must be add or remove")
    if not login or not all(c.isalnum() or c in "-_" for c in login):
        raise ChangeError(f"'{login}' is not a GitHub login")

    path = SEI_DIR / f"{name}.json"
    if not path.exists():
        raise ChangeError(f"'{name}' is not registered")
    entry = json.loads(path.read_text(encoding="utf-8"))
    maintainers = entry.get("maintainers") or []

    sender = os.environ.get("SENDER", "")
    if not sender:
        raise ChangeError("SENDER is not set")
    if f"github:{sender}" not in maintainers:
        raise ChangeError(f"{sender} is not a maintainer of '{name}'")

    target = f"github:{login}"
    if action == "add":
        if target in maintainers:
            raise ChangeError(f"{login} is already a maintainer of '{name}'")
        if len(maintainers) >= MAX:
            raise ChangeError(f"'{name}' already has {MAX} maintainers")
        maintainers.append(target)
    else:
        if target not in maintainers:
            raise ChangeError(f"{login} is not a maintainer of '{name}'")
        if len(maintainers) == 1 and not os.environ.get("APPROVED"):
            raise ChangeError(
                "removing the last maintainer needs a maintainer of this index "
                "to add the 'maintainers-approved' label"
            )
        maintainers.remove(target)

    entry["maintainers"] = maintainers
    path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"::notice::{name} maintainers: {', '.join(maintainers)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ChangeError as ex:
        print(f"::error::{ex}")
        raise SystemExit(1)
