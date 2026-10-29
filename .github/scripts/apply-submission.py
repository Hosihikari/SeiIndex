#!/usr/bin/env python3
"""Turn an issue-form submission into an index entry.

Reads the issue body from ISSUE_BODY, appends the submitted version to
sei/<name>.json, and adds the name to index.json. Writes ok/looks/name/version/
error to $GITHUB_OUTPUT. This script only parses and validates shape; the
authoritative check is `sk index verify --check-artifacts --strict`.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

NAME_FORBIDDEN = set('/\\:*?"<>|')
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ENTRY_KEYS = {"version", "dependencies", "artifacts", "yanked", "deprecated"}
ARTIFACT_KEYS = {"selectors", "layout", "source"}
SOURCE_KEYS = {"url", "sha256", "size"}


class SubmissionError(Exception):
    pass


def valid_name(name: str) -> bool:
    if not name or name in (".", ".."):
        return False
    if name[0] in " ." or name[-1] in " .":
        return False
    return all(ord(char) >= 0x20 and char not in NAME_FORBIDDEN for char in name)


def section(body: str, label: str) -> str | None:
    pattern = re.compile(
        r"^###\s+" + re.escape(label) + r"\s*$(.*?)(?=^###\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(body)
    return match.group(1).strip() if match else None


def extract_json(text: str):
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    raw = match.group(1) if match else text
    try:
        return json.loads(raw)
    except json.JSONDecodeError as ex:
        raise SubmissionError(f"invalid JSON: {ex}") from ex


def validate_entry(entry, name: str) -> None:
    if not isinstance(entry, dict):
        raise SubmissionError("version entry must be a JSON object")
    unknown = set(entry) - ENTRY_KEYS
    if unknown:
        raise SubmissionError(f"unknown fields in version entry: {', '.join(sorted(unknown))}")

    version = entry.get("version")
    if not isinstance(version, str) or not SEMVER.match(version):
        raise SubmissionError("version must be a SemVer string such as 1.2.0")

    dependencies = entry.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise SubmissionError("dependencies must be an array")
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise SubmissionError("each dependency must be an object")
        dep_name = dependency.get("name")
        if not isinstance(dep_name, str) or not valid_name(dep_name):
            raise SubmissionError(f"invalid dependency name: {dep_name!r}")
        if dep_name == name:
            raise SubmissionError("a sei cannot depend on itself")
        dep_version = dependency.get("version")
        if dep_version is not None and not isinstance(dep_version, str):
            raise SubmissionError(f"invalid version range for {dep_name}")

    artifacts = entry.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise SubmissionError("artifacts must be a non-empty array")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise SubmissionError("each artifact must be an object")
        unknown = set(artifact) - ARTIFACT_KEYS
        if unknown:
            raise SubmissionError(f"unknown artifact fields: {', '.join(sorted(unknown))}")
        layout = artifact.get("layout")
        if layout not in (None, "root"):
            raise SubmissionError(f"unsupported layout: {layout!r}")
        selectors = artifact.get("selectors")
        if selectors is not None:
            if not isinstance(selectors, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in selectors.items()
            ):
                raise SubmissionError("selectors must map strings to strings")
        source = artifact.get("source")
        if not isinstance(source, dict):
            raise SubmissionError("artifact source must be an object")
        unknown = set(source) - SOURCE_KEYS
        if unknown:
            raise SubmissionError(f"unknown source fields: {', '.join(sorted(unknown))}")
        url = source.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise SubmissionError("artifact url must start with https://")
        sha256 = source.get("sha256")
        if not isinstance(sha256, str) or not SHA256.match(sha256):
            raise SubmissionError("sha256 must be 64 lowercase hexadecimal characters")
        size = source.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise SubmissionError("size must be a positive integer")

    if "yanked" in entry and not isinstance(entry["yanked"], bool):
        raise SubmissionError("yanked must be a boolean")
    if "deprecated" in entry and entry["deprecated"] is not None and not isinstance(
        entry["deprecated"], str
    ):
        raise SubmissionError("deprecated must be a string")


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def apply(body: str) -> tuple[str, str]:
    name_section = section(body, "Sei name")
    entry_section = section(body, "Version entry (JSON)")
    if name_section is None or entry_section is None:
        raise SubmissionError("missing the submission form fields")

    name = name_section.splitlines()[0].strip() if name_section else ""
    if not valid_name(name):
        raise SubmissionError(f"invalid sei name: {name!r}")

    entry = extract_json(entry_section)
    validate_entry(entry, name)
    version = entry["version"]

    index_path = Path("index.json")
    if not index_path.exists():
        raise SubmissionError("index.json not found; run from the index root")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("schemaVersion") != 1:
        raise SubmissionError("unsupported index schemaVersion")

    sei_path = Path("sei") / f"{name}.json"
    if sei_path.exists():
        sei = json.loads(sei_path.read_text(encoding="utf-8"))
        if sei.get("schemaVersion") != 1:
            raise SubmissionError(f"unsupported schemaVersion in {sei_path}")
        if sei.get("name") != name:
            raise SubmissionError(f"{sei_path} declares name {sei.get('name')!r}")
    else:
        sei = {"schemaVersion": 1, "name": name, "versions": []}

    versions = sei.get("versions")
    if not isinstance(versions, list):
        raise SubmissionError(f"{sei_path} has no versions array")
    if any(item.get("version") == version for item in versions if isinstance(item, dict)):
        raise SubmissionError(f"{name} {version} already exists; versions are immutable")

    versions.append(entry)
    names = list(index.get("sei") or [])
    if name not in names:
        names.append(name)
    index["sei"] = sorted(names)

    sei_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(sei_path, sei)
    write_json(index_path, index)
    return name, version


def main() -> int:
    body = os.environ.get("ISSUE_BODY", "")
    looks = section(body, "Sei name") is not None and section(body, "Version entry (JSON)") is not None
    ok = False
    name = ""
    version = ""
    error = ""
    try:
        if not looks:
            raise SubmissionError("this issue does not contain the submission form")
        name, version = apply(body)
        ok = True
    except SubmissionError as ex:
        error = str(ex)
    except Exception as ex:  # noqa: BLE001 - report any failure back to the issue
        error = f"unexpected error: {ex}"

    outputs = {
        "ok": str(ok).lower(),
        "looks": str(looks).lower(),
        "name": name,
        "version": version,
        "error": " ".join(error.split()),
    }
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as stream:
            for key, value in outputs.items():
                stream.write(f"{key}={value}\n")
    else:
        print(outputs)
    if not ok and looks:
        print(f"submission rejected: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
