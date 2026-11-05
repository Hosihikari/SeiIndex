#!/usr/bin/env python3
"""Merge release artifacts into a maintainer's sei-index.json (ADR-0041).

Each artifact is a zip whose root carries `sei.json`. The version entry is
built from that manifest and the index entry the maintainer already has; the
public URL, digest and size come from this script, never from the manifest.

Rules:
* a version that already exists with the same artifacts is a no-op,
* a version that exists with different artifacts fails (versions are immutable),
* `project`, `unlisted` and `deprecated` are preserved,
* `upstream`, `maintainers` and `source*` must not be present.

Usage: build-package-index.py <sei-index.json> <spec.json>

The spec is a JSON array of {rid, path, url}. `rid` may be null.
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

MAX_MANIFEST = 1 << 20


class BuildError(Exception):
    pass


def read_manifest(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        try:
            data = archive.read("sei.json")
        except KeyError as ex:
            raise BuildError(f"{path.name}: archive has no root sei.json") from ex
    if len(data) > MAX_MANIFEST:
        raise BuildError(f"{path.name}: sei.json is larger than {MAX_MANIFEST} bytes")
    return json.loads(data)


def relations(value, label: str) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise BuildError(f"{label} must be an array")
    out = []
    for item in value:
        if not isinstance(item, dict) or not item.get("name"):
            raise BuildError(f"{label} has an entry without a name")
        out.append({"name": item["name"], **({"version": item["version"]} if item.get("version") else {})})
    return out


def build_artifact(spec: dict) -> tuple[dict, dict]:
    path = Path(spec["path"])
    if not path.is_file():
        raise BuildError(f"artifact not found: {path}")
    url = spec["url"]
    if not url.startswith("https://"):
        raise BuildError(f"artifact URL must start with https://: {url}")

    manifest = read_manifest(path)
    artifact_manifest = manifest.get("artifact")
    if not isinstance(artifact_manifest, dict):
        raise BuildError(f"{path.name}: sei.json has no artifact object")

    rid = spec.get("rid") or artifact_manifest.get("rid")
    if spec.get("rid") and artifact_manifest.get("rid") and spec["rid"] != artifact_manifest["rid"]:
        raise BuildError(
            f"{path.name}: rid '{artifact_manifest['rid']}' in sei.json vs '{spec['rid']}' in the workflow"
        )
    layout = artifact_manifest.get("layout") or "root"
    if layout != "root":
        raise BuildError(f"{path.name}: unsupported layout '{layout}'")

    entry = {
        "dependencies": relations(artifact_manifest.get("dependencies"), "artifact dependencies"),
        "prerequisites": relations(artifact_manifest.get("prerequisites"), "artifact prerequisites"),
        "optionalPeers": relations(artifact_manifest.get("optionalPeers"), "artifact optional peers"),
        "conflicts": relations(artifact_manifest.get("conflicts"), "artifact conflicts"),
        "layout": "root",
    }
    if rid:
        entry = {"rid": rid, **entry}
    if artifact_manifest.get("modes"):
        entry["modes"] = artifact_manifest["modes"]

    data = path.read_bytes()
    entry["source"] = {
        "url": url,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }
    version = {
        "version": manifest.get("version"),
        "dependencies": relations(manifest.get("dependencies"), "dependencies"),
        "prerequisites": relations(manifest.get("prerequisites"), "prerequisites"),
        "optionalPeers": relations(manifest.get("optionalPeers"), "optional peers"),
        "conflicts": relations(manifest.get("conflicts"), "conflicts"),
        "artifacts": [entry],
    }
    identity = {"name": manifest.get("name"), "versions": [version]}
    return identity, entry


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: build-package-index.py <sei-index.json> <spec.json>", file=sys.stderr)
        return 2

    target = Path(sys.argv[1])
    specs = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    if not isinstance(specs, list) or not specs:
        raise BuildError("the artifact spec must be a non-empty array")

    index = None
    if target.exists():
        index = json.loads(target.read_text(encoding="utf-8"))
        for key in ("upstream", "maintainers", "sourceUnlisted", "sourceDeprecated"):
            if key in index:
                raise BuildError(f"{target.name} declares the index-side field '{key}'")
        for version in index.get("versions") or []:
            for key in ("sourceYanked", "sourceAdvisories"):
                if key in version:
                    raise BuildError(f"{target.name} version '{version.get('version')}' declares '{key}'")

    if index is None:
        first, _ = build_artifact(specs[0])
        index = {
            "schemaVersion": 2,
            "name": first["name"],
            "versions": [],
        }

    by_version = {item.get("version"): item for item in index["versions"]}
    added = 0
    for spec in specs:
        identity, artifact = build_artifact(spec)
        if identity["name"] != index["name"]:
            raise BuildError(f"sei.json name '{identity['name']}' does not match '{index['name']}'")
        version = identity["versions"][0]
        if not version["version"]:
            raise BuildError(f"{spec['path']}: sei.json has no version")

        existing = by_version.get(version["version"])
        if existing is None:
            index["versions"].append(version)
            by_version[version["version"]] = version
            added += 1
            continue

        # Same version: only the artifact list may grow, and identical input
        # means nothing to do.
        others = {k: v for k, v in version.items() if k != "artifacts"}
        current = {k: v for k, v in existing.items() if k not in ("artifacts", "yanked", "deprecated", "advisory")}
        if others != current:
            raise BuildError(
                f"version '{version['version']}' changed; bump the version instead of editing it"
            )
        if artifact not in existing["artifacts"]:
            if any(item.get("rid") == artifact.get("rid")
                   and item.get("prerequisites") == artifact.get("prerequisites")
                   for item in existing["artifacts"]):
                raise BuildError(
                    f"version '{version['version']}' already has a different artifact for "
                    f"rid '{artifact.get('rid')}'; bump the version"
                )
            existing["artifacts"].append(artifact)
            added += 1

    index["versions"].sort(key=lambda item: item["version"])
    target.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{target}: {added} artifact(s) written" + (" (no change)" if added == 0 else ""))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as ex:
        print(f"::error::{ex}")
        raise SystemExit(1)
