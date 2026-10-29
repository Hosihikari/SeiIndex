# SeiIndex

The official static index for [Seiko](https://github.com/Hosihikari/Seiko). Seiko consumes it as an ordinary source:

```hocon
sources = [
  { id = "official", index = "https://raw.githubusercontent.com/Hosihikari/SeiIndex/main/index.json" }
]
```

`sk init` writes this source by default. The URL is only a default: any static HTTPS index or local directory with the same layout works, and private indexes use the same format.

## Layout

```
index.json          schemaVersion, generatedBy, and the sei name list used by `sk search`
sei/<name>.json     all versions of one sei and their artifacts
```

Any project can submit its own `sei/<name>.json` through the submission issue form; the index bot turns it into a pull request. There is no `sk publish`; hosting the artifact is up to the producer, and this repository only points at stable URLs and checksums.

## Submitting a sei

1. Build a zip whose root contains `sei.json` and the payload. Nested directories are allowed; the payload paths are deployed relative to the install root.
2. Host the zip at a stable, public URL. A GitHub Release asset pinned to a tag is the simplest option; object storage and static sites work too.
3. Open a **Submit a sei version** issue: https://github.com/Hosihikari/SeiIndex/issues/new?template=sei-submission.yml. Enter the sei name and the complete version entry as JSON (artifacts, optional dependencies and selectors).
4. Members and collaborators are processed automatically. Other authors need a maintainer to add the `index-submission` label.
5. The index bot appends the entry to `sei/<name>.json`, adds the name to `index.json`, opens a pull request, dispatches **Validate index**, and enables auto-merge. The pull request merges when validation passes, and the issue closes on merge.

Pull requests are not the submission channel. Pull requests from outside the organization that only touch index data are closed with a pointer to the issue form; maintainers can still use pull requests for other changes. The index bot's pull requests are data-only and are never authored by an external contributor.

## Merging

Data-only pull requests from members and bots have GitHub auto-merge enabled automatically. Once the `validate` check from **Validate index** passes, they are squash-merged without further review.

Pull requests that touch anything else, including `.github/` and this README, are not auto-merged; a maintainer reviews and merges those. This keeps CI changes out of automatic merges, since a pull request that can edit the workflow could otherwise satisfy its own checks.

A sei name must be path-safe: no `/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`, no control characters, and no leading or trailing space or dot. The file name, the `name` field, and the entry in `index.json` must all match.

## Rules

- **Versions are immutable.** Append new versions; never edit an existing version entry or remove one.
- **Only `yanked` and `deprecated` may change in an existing version.** `yanked: true` hides a version from new resolutions but keeps it available for lock replay; `deprecated` is a human-readable migration message.
- **Never delete a sei or a version.** Yanking or deprecating is the retirement path.
- **The `sei` list in `index.json` may only grow.** Removing a name breaks search and is rejected.
- **Artifacts must be zip archives** with exactly one root `sei.json` (the current store extracts zip only).
- **The index entry must match the embedded `sei.json`** for `schemaVersion`, `name`, `version`, `dependencies`, `selectors`, and `layout`.
- **Checksums are exact.** `sha256` is 64 lowercase hex characters and `size` is the archive size in bytes; CI downloads every artifact and verifies both.

## Schema

`index.json`:

```json
{
  "schemaVersion": 1,
  "generatedBy": "SeiIndex maintainers",
  "sei": ["hello-csharp"]
}
```

`sei/hello-csharp.json`:

```json
{
  "schemaVersion": 1,
  "name": "hello-csharp",
  "versions": [
    {
      "version": "1.0.0",
      "dependencies": [
        { "name": "hosihikari", "version": "[1.1.0,1.2.0)" }
      ],
      "artifacts": [
        {
          "selectors": { "rid": "win-x64" },
          "layout": "root",
          "source": {
            "url": "https://github.com/example/hello-csharp/releases/download/v1.0.0/hello-csharp-win-x64.zip",
            "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "size": 12345
          }
        }
      ],
      "yanked": false,
      "deprecated": null
    }
  ]
}
```

The zip's root `sei.json` for that artifact:

```json
{
  "schemaVersion": 1,
  "name": "hello-csharp",
  "version": "1.0.0",
  "dependencies": [
    { "name": "hosihikari", "version": "[1.1.0,1.2.0)" }
  ],
  "selectors": { "rid": "win-x64" },
  "layout": "root",
  "modes": { "hello-csharp": "0755" }
}
```

Fields:

- `version` uses NuGet SemVer. Pre-releases are excluded unless the declaration asks for them.
- `dependencies[].version` is a NuGet version range; `null`, omitted, or `"*"` means any version.
- `selectors.rid` matches the target platform, for example `win-x64` or `linux-arm64`. Any other selector key names a sei that must be in the dependency graph (the `carrier` convention). Omit `selectors` for a platform-independent artifact.
- `layout` is `root` (or omitted). Other shapes are not supported yet.
- `modes` belongs to `sei.json` only; it sets Unix executable bits, for example `{ "sk": "0755" }`. Windows ignores it.

Every version needs at least one artifact, and two artifacts in one version cannot have identical selectors.

## Verify locally

```bash
sk index verify . --check-artifacts --strict
```

The command prints findings and exits non-zero on errors (or on warnings with `--strict`). `--json` emits the usual Seiko envelope. CI runs the same command with a pinned `sk` version, plus `git diff` checks for the append-only rules.
