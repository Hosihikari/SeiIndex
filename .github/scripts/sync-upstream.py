#!/usr/bin/env python3
"""Fetch a maintainer's sei-index.json and merge it into the index.

This is the mirror side of ADR-0033. The upstream file is the maintainer's
source of truth; the index keeps a strict, append-only mirror of it:

* versions already published may not be rewritten or removed,
* new versions are appended,
* project, unlisted and deprecation text may change,
* the source overlay (source*) belongs to the index and is preserved,
* `upstream` and `maintainers` are index-side and never come from the file.

Usage:
    sync-upstream.py <name> [--from-registration]
    sync-upstream.py --all

Writes the merged `sei/<name>.json` and refreshes `catalog.json`. Prints
`result=<noop|updated>` to $GITHUB_OUTPUT when available. Exits 1 when the
upstream cannot be read or the change violates the append rules.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEI_DIR = ROOT / "sei"
INDEX = ROOT / "index.json"
SK = Path(os.environ.get("SK_BIN", "sk"))
FILE_NAME = "sei-index.json"
MAX_BYTES = 1 << 20
MUTABLE_VERSION_KEYS = {"yanked", "deprecated", "advisory", "sourceYanked", "sourceAdvisories"}
MUTABLE_PACKAGE_KEYS = {"project", "unlisted", "deprecated", "sourceUnlisted", "sourceDeprecated"}
SIDE_KEYS = {"upstream", "maintainers", "sourceUnlisted", "sourceDeprecated", "sourceYanked", "sourceAdvisories"}
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


class SyncError(Exception):
    pass


def output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{key}={value}\n")


def comment(body: str) -> None:
    print(body)


def is_public_https(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            return False
    return True


class HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != "https":
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> bytes:
    if not is_public_https(url):
        raise SyncError(f"upstream must be a public https URL without credentials: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "SeiIndex-sync"})
    opener = urllib.request.build_opener(HttpsOnlyRedirects)
    context = ssl.create_default_context()
    try:
        with opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise SyncError(f"upstream returned HTTP {response.status}")
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as ex:
        raise SyncError(f"upstream returned HTTP {ex.code}") from ex
    except urllib.error.URLError as ex:
        raise SyncError(f"cannot reach upstream: {ex.reason}") from ex
    if len(data) > MAX_BYTES:
        raise SyncError(f"upstream is larger than {MAX_BYTES} bytes")
    return data


def sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def verify(path: Path) -> None:
    """Run the same structural rules the CI runs, so a bad file never merges."""
    result = subprocess.run(
        [str(SK), "index", "verify", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SyncError(f"{FILE_NAME} failed verification:\n{result.stdout}{result.stderr}")


def strip(entry: dict, keys: set[str]) -> dict:
    return {key: value for key, value in entry.items() if key not in keys}


def merge_package(name: str, upstream: dict, existing: dict | None, maintainers: list[str]) -> dict:
    entry_name = upstream.get("name")
    if entry_name != name:
        raise SyncError(f"upstream declares name '{entry_name}', expected '{name}'")

    project = upstream.get("project")
    if not isinstance(project, dict):
        raise SyncError("upstream has no project metadata")

    incoming = upstream.get("versions") or []
    if not incoming:
        raise SyncError("upstream has no versions")

    for new in incoming:
        for key in SIDE_KEYS:
            if key in new:
                raise SyncError(f"upstream must not declare '{key}' at version scope")

    old_versions = (existing or {}).get("versions") or []
    by_version = {item.get("version"): item for item in old_versions}
    merged = []
    added = 0

    for position, old in enumerate(old_versions):
        if position >= len(incoming):
            raise SyncError(
                f"version '{old.get('version')}' disappeared from upstream; "
                "yank it instead of deleting it"
            )
        new = incoming[position]
        if old.get("version") != new.get("version"):
            raise SyncError(
                f"version order changed at position {position}; "
                f"index has '{old.get('version')}', upstream has '{new.get('version')}'"
            )
        if strip(old, MUTABLE_VERSION_KEYS) != strip(new, MUTABLE_VERSION_KEYS):
            raise SyncError(f"version '{old.get('version')}' was rewritten; publish a new version")
        merged.append(apply_overlay(old, new))

    for new in incoming[len(old_versions):]:
        version = new.get("version")
        if version in by_version:
            raise SyncError(f"version '{version}' was inserted out of order")
        if not SEMVER.match(str(version)):
            raise SyncError(f"upstream has an invalid version '{version}'")
        merged.append(new)
        added += 1

    result = {
        "schemaVersion": 2,
        "name": name,
        "project": project,
        "unlisted": upstream.get("unlisted") or bool((existing or {}).get("unlisted")),
        "upstream": (existing or {}).get("upstream") or {"url": "", "sha256": ""},
        "maintainers": maintainers,
        "versions": merged,
    }
    if upstream.get("deprecated") is not None:
        result["deprecated"] = upstream["deprecated"]
    if (existing or {}).get("sourceUnlisted") is not None:
        result["sourceUnlisted"] = existing["sourceUnlisted"]
    if (existing or {}).get("sourceDeprecated") is not None:
        result["sourceDeprecated"] = existing["sourceDeprecated"]
    result["_added"] = added
    return result


def apply_overlay(old: dict, new: dict) -> dict:
    merged = dict(new)
    for key in ("sourceYanked", "sourceAdvisories"):
        if key in old:
            merged[key] = old[key]
    return merged


def current_url(existing: dict | None) -> str | None:
    upstream = (existing or {}).get("upstream") or {}
    url = upstream.get("url")
    return url or None


def sync_one(name: str, url: str | None, registration: bool) -> str:
    path = SEI_DIR / f"{name}.json"
    existing = load(path) if path.exists() else None
    if existing is None and not registration:
        raise SyncError(f"'{name}' is not registered")
    if existing is not None and not registration and not (existing.get("maintainers") or []):
        raise SyncError(f"'{name}' has no maintainers")

    url = url or current_url(existing)
    if not url:
        raise SyncError(f"'{name}' has no upstream URL")

    data = fetch(url)
    digest = sha256(data)
    if existing is not None:
        recorded = ((existing.get("upstream") or {}).get("sha256")) or ""
        if recorded == digest:
            output("result", "noop")
            return "noop"

    with tempfile.TemporaryDirectory() as directory:
        staged = Path(directory) / FILE_NAME
        staged.write_bytes(data)
        # A maintainer file may not carry the index-side fields.
        verify(staged)
        upstream = load(staged)

    maintainers = (existing or {}).get("maintainers") or [
        f"github:{os.environ['SENDER']}" if os.environ.get("SENDER") else "github:unknown"
    ]
    if registration:
        actor = os.environ.get("SENDER")
        if not actor:
            raise SyncError("registration needs SENDER")
        maintainers = [f"github:{actor}"]

    merged = merge_package(name, upstream, existing, maintainers)
    added = merged.pop("_added")
    merged["upstream"] = {"url": url, "sha256": digest}
    write(path, merged)

    if existing is None:
        index = load(INDEX)
        names = index.get("sei") or []
        if name not in names:
            names.append(name)
            index["sei"] = sorted(names)
            write(INDEX, index)

    subprocess.run([str(SK), "index", "catalog", str(ROOT)], check=True, capture_output=True)
    output("result", "updated")
    print(f"{name}: {added} new version(s), upstream {digest}")
    return "updated"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    registration = "--from-registration" in sys.argv
    try:
        if "--all" in sys.argv:
            for path in sorted(SEI_DIR.glob("*.json")):
                sync_one(path.stem, current_url(load(path)), registration=False)
        else:
            if len(args) != 1:
                print("usage: sync-upstream.py <name> [--from-registration] | --all", file=sys.stderr)
                return 2
            sync_one(args[0], os.environ.get("UPSTREAM_URL"), registration)
    except SyncError as ex:
        output("result", "failed")
        print(f"::error::{ex}")
        comment(str(ex))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
