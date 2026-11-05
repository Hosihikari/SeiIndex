#!/usr/bin/env python3
"""Rewrite schema-1 artifact manifests to schema 2 (0.3 migration, ADR-0030).

For every artifact in the index: download, rewrite the root sei.json to the
schema-2 shape (selectors.carrier -> artifact prerequisites, selectors.rid ->
artifact.rid, layout -> artifact.layout), rebuild the zip, upload it back to
the same release asset, and record the new digest and size in the index.

Dry run by default; pass --apply to upload and rewrite the index.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEI_DIR = ROOT / "sei"
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""


def download(url: str) -> bytes:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": PROXY, "http": PROXY}) if PROXY else urllib.request.ProxyHandler({})
    )
    request = urllib.request.Request(url, headers={"User-Agent": "SeiIndex-migration"})
    with opener.open(request, timeout=120) as response:
        return response.read()


def migrate(manifest: dict, artifact: dict) -> dict:
    if manifest.get("schemaVersion") != 1:
        return manifest
    selectors = manifest.pop("selectors", {}) or {}
    out = {
        "schemaVersion": 2,
        "name": manifest["name"],
        "version": manifest["version"],
        "dependencies": manifest.get("dependencies", []),
        "prerequisites": manifest.get("prerequisites", []),
        "optionalPeers": manifest.get("optionalPeers", []),
        "conflicts": manifest.get("conflicts", []),
        "artifact": {
            "rid": selectors.get("rid") or artifact.get("rid"),
            "dependencies": [],
            "prerequisites": (
                [{"name": selectors["carrier"], "version": "*"}] if selectors.get("carrier") else []
            ),
            "optionalPeers": [],
            "conflicts": [],
            "layout": manifest.get("layout", "root"),
        },
    }
    if manifest.get("modes"):
        out["artifact"]["modes"] = manifest["modes"]
    return out


def rebuilt(data: bytes, manifest: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(
        buffer, "w", zipfile.ZIP_DEFLATED
    ) as target:
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == "sei.json":
                payload = (json.dumps(manifest, indent=2) + "\n").encode()
            info = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            info.external_attr = item.external_attr
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, payload)
    return buffer.getvalue()


def upload(url: str, path: Path) -> None:
    # https://github.com/<owner>/<repo>/releases/download/<tag>/<asset>
    parts = url.split("/")
    owner, repo, tag, asset = parts[3], parts[4], parts[7], parts[9]
    subprocess.run(
        ["gh", "release", "upload", f"{tag}", "--repo", f"{owner}/{repo}", str(path), "--clobber"],
        check=True,
        capture_output=True,
        env={**os.environ, "HTTPS_PROXY": PROXY, "https_proxy": PROXY},
    )


def main() -> int:
    apply = "--apply" in sys.argv
    import hashlib

    changed = 0
    for path in sorted(SEI_DIR.glob("*.json")):
        index = json.loads(path.read_text(encoding="utf-8"))
        touched = False
        for version in index["versions"]:
            for artifact in version["artifacts"]:
                source = artifact["source"]
                data = download(source["url"])
                digest = hashlib.sha256(data).hexdigest()
                if digest != source["sha256"]:
                    print(f"!! digest drift for {source['url']}")
                    return 1
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    manifest = json.loads(archive.read("sei.json"))
                if manifest.get("schemaVersion") != 1:
                    continue
                migrated = migrate(manifest, artifact)
                # The rewritten manifest must describe exactly what the index
                # says, or the 0.3 validator would reject it.
                expect = {
                    "rid": artifact.get("rid"),
                    "prerequisites": artifact.get("prerequisites", []),
                    "dependencies": artifact.get("dependencies", []),
                    "layout": artifact.get("layout", "root"),
                }
                actual = {
                    "rid": migrated["artifact"]["rid"],
                    "prerequisites": migrated["artifact"]["prerequisites"],
                    "dependencies": migrated["artifact"]["dependencies"],
                    "layout": migrated["artifact"]["layout"],
                }
                if expect != actual:
                    print(f"!! mismatch for {source['url']}\n   index={expect}\n   file={actual}")
                    return 1
                out = rebuilt(data, migrated)
                source["sha256"] = hashlib.sha256(out).hexdigest()
                source["size"] = len(out)
                touched = True
                changed += 1
                print(f"{'upload' if apply else 'would upload'} {source['url']} -> {source['sha256'][:12]}")
                if apply:
                    with tempfile.TemporaryDirectory() as directory:
                        staged = Path(directory) / source["url"].rsplit("/", 1)[1]
                        staged.write_bytes(out)
                        upload(source["url"], staged)
        if touched and apply:
            path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"{changed} artifact(s) {'migrated' if apply else 'would be migrated'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
