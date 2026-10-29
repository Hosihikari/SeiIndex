#!/usr/bin/env python3
"""Reject index changes that rewrite published history.

Usage: check-append-only.py <base-ref>

A pull request may add sei files, append versions, change yanked/deprecated,
and add names to the root list. It may not delete files or versions, rewrite
an existing version, or remove a name from the root list.
"""

from __future__ import annotations

import json
import subprocess
import sys

MUTABLE_KEYS = {"yanked", "deprecated"}
ZERO = "0" * 40


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
    ).stdout


def read(ref: str, path: str):
    try:
        raw = git("show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # The sk index verify step reports parse errors with more context.
        return None


def changed_pairs(base: str) -> list[tuple[str, str]]:
    raw = git(
        "diff",
        "--name-status",
        "--no-renames",
        "-z",
        base,
        "HEAD",
        "--",
        "index.json",
        "sei",
    )
    tokens = raw.split(b"\0")
    pairs: list[tuple[str, str]] = []
    for index in range(0, len(tokens) - 1, 2):
        status = tokens[index].decode()
        path = tokens[index + 1].decode()
        if status and path:
            pairs.append((status, path))
    return pairs


def check_root(base: str, failures: list[str]) -> None:
    old = read(base, "index.json")
    new = read("HEAD", "index.json")
    if new is None:
        failures.append("index.json was deleted")
        return
    if old is None:
        return
    if old.get("schemaVersion") != new.get("schemaVersion"):
        failures.append("index.json: schemaVersion changed")
    new_names = set(new.get("sei") or [])
    for name in old.get("sei") or []:
        if name not in new_names:
            failures.append(f"index.json: removed sei '{name}'")


def check_sei(base: str, path: str, status: str, failures: list[str]) -> None:
    if status == "D":
        failures.append(f"{path}: deleting a sei file is not allowed")
        return

    old = read(base, path)
    new = read("HEAD", path)
    if new is None:
        failures.append(f"{path}: deleting a sei file is not allowed")
        return
    if old is None:
        return

    if old.get("schemaVersion") != new.get("schemaVersion"):
        failures.append(f"{path}: schemaVersion changed")
    if old.get("name") != new.get("name"):
        failures.append(f"{path}: name changed")

    old_versions = old.get("versions") or []
    new_versions = new.get("versions") or []
    if len(new_versions) < len(old_versions):
        failures.append(f"{path}: versions were removed")
        return

    for position, old_entry in enumerate(old_versions):
        new_entry = new_versions[position]
        if strip(old_entry) != strip(new_entry):
            version = old_entry.get("version", f"#{position}")
            failures.append(
                f"{path}: version '{version}' was modified; append a new version instead"
            )


def strip(entry: dict) -> dict:
    return {key: value for key, value in entry.items() if key not in MUTABLE_KEYS}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check-append-only.py <base-ref>", file=sys.stderr)
        return 2

    base = sys.argv[1]
    if not base or base == ZERO:
        # The first push to a branch has no base to compare against.
        return 0

    try:
        pairs = changed_pairs(base)
    except subprocess.CalledProcessError as ex:
        print(f"cannot diff against {base}: {ex}", file=sys.stderr)
        return 2

    failures: list[str] = []
    for status, path in pairs:
        if path == "index.json":
            check_root(base, failures)
        elif path.startswith("sei/") and path.endswith(".json"):
            check_sei(base, path, status, failures)

    for failure in failures:
        print(f"append-only: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
