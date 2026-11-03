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
ENTRY_KEYS = {"version", "dependencies", "prerequisites", "optionalPeers", "conflicts", "artifacts", "yanked", "deprecated", "advisory"}
ARTIFACT_KEYS = {"rid", "dependencies", "prerequisites", "optionalPeers", "conflicts", "layout", "modes", "source"}
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

    advisory = entry.get("advisory")
    if advisory is not None:
        if not isinstance(advisory, dict):
            raise SubmissionError("advisory must be a JSON object")
        unknown_advisory = set(advisory) - {"severity", "url"}
        if unknown_advisory:
            raise SubmissionError(
                f"unknown fields in advisory: {', '.join(sorted(unknown_advisory))}")
        if advisory.get("severity") not in {"low", "moderate", "high", "critical"}:
            raise SubmissionError("advisory severity must be low, moderate, high, or critical")
        url = advisory.get("url")
        if url is not None and not isinstance(url, str):
            raise SubmissionError("advisory url must be a string")

    validate_relations(entry.get("dependencies", []), name, "dependencies", self_allowed=False)
    validate_relations(entry.get("prerequisites", []), name, "prerequisites", self_allowed=False)
    validate_relations(entry.get("optionalPeers", []), name, "optionalPeers", self_allowed=False)
    validate_relations(entry.get("conflicts", []), name, "conflicts", self_allowed=False)

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
        rid = artifact.get("rid")
        if rid is not None and (not isinstance(rid, str) or not rid.strip()):
            raise SubmissionError("rid must be a non-empty string")
        validate_relations(artifact.get("dependencies", []), name, "artifact dependencies", self_allowed=True)
        validate_relations(artifact.get("prerequisites", []), name, "artifact prerequisites", self_allowed=True)
        validate_relations(artifact.get("optionalPeers", []), name, "artifact optional peers", self_allowed=True)
        validate_relations(artifact.get("conflicts", []), name, "artifact conflicts", self_allowed=True)
        modes = artifact.get("modes")
        if modes is not None:
            if not isinstance(modes, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in modes.items()
            ):
                raise SubmissionError("modes must map paths to mode strings")
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


def validate_relations(relations, name: str, label: str, self_allowed: bool) -> None:
    if not isinstance(relations, list):
        raise SubmissionError(f"{label} must be an array")
    for relation in relations:
        if not isinstance(relation, dict):
            raise SubmissionError(f"each entry in {label} must be an object")
        target = relation.get("name")
        if not isinstance(target, str) or not valid_name(target):
            raise SubmissionError(f"invalid name in {label}: {target!r}")
        if target == name and not self_allowed:
            raise SubmissionError(f"{label} cannot contain the sei itself")
        version = relation.get("version")
        if version is not None and not isinstance(version, str):
            raise SubmissionError(f"invalid version range for {target}")


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
    if index.get("schemaVersion") != 2:
        raise SubmissionError("unsupported index schemaVersion")

    sei_path = Path("sei") / f"{name}.json"
    if sei_path.exists():
        sei = json.loads(sei_path.read_text(encoding="utf-8"))
        if sei.get("schemaVersion") != 2:
            raise SubmissionError(f"unsupported schemaVersion in {sei_path}")
        if sei.get("name") != name:
            raise SubmissionError(f"{sei_path} declares name {sei.get('name')!r}")
    else:
        sei = {"schemaVersion": 2, "name": name, "versions": []}

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
