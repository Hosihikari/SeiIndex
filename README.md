# SeiIndex

[English](README.md) | [简体中文](README.zh_hans.md)

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
3. Open a **Submit a sei version** issue: https://github.com/Hosihikari/SeiIndex/issues/new?template=sei-submission.yml. Enter the sei name and the complete version entry as JSON (artifacts and optional relations).
4. Accounts with write access to this repository are processed automatically. Other authors need a maintainer to add the `index-submission` label.
5. The index bot appends the entry to `sei/<name>.json`, adds the name to `index.json`, opens a pull request, approves the **Validate index** run GitHub holds for it, and enables auto-merge. The pull request merges when validation passes, and the submission job closes the issue after the merge.

Pull requests are not the submission channel. Pull requests from outside the organization that only touch index data are closed with a pointer to the issue form; maintainers can still use pull requests for other changes. The index bot's pull requests are data-only and are never authored by an external contributor.

The submission issue is labeled `validation-pending` while the pull request is being validated, `validation-failed` if validation does not pass, and `validation-passed` once it does. The pull request body contains `Closes #<issue>` for human merges; because auto-merge runs as the bot, the submission job closes the issue explicitly once the merge lands. Submission issues that do not pass validation within 30 days are closed as not planned.

## Merging

Data-only pull requests from accounts with write access and from bots have GitHub auto-merge enabled automatically. Once the `validate` check from **Validate index** passes, they are squash-merged without further review.

Pull requests that touch anything else, including `.github/` and this README, are not auto-merged; a maintainer reviews and merges those. This keeps CI changes out of automatic merges, since a pull request that can edit the workflow could otherwise satisfy its own checks.

A sei name must be path-safe: no `/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`, no control characters, and no leading or trailing space or dot. The file name, the `name` field, and the entry in `index.json` must all match.

## Project metadata

Each `sei/<name>.json` carries a `project` object that the client shows in `sk search` and `sk info`:

| Field | Meaning |
| --- | --- |
| `description` | Required. One line, shown in search results. |
| `authors` | Required. Display names, not accounts. |
| `license` | Required. An SPDX expression such as `MIT` or `GPL-3.0-only`. |
| `tags` | Optional labels for `sk search --tag`. |
| `projectUrl` | Optional HTTPS project page. |
| `repositoryUrl`, `repositoryType` | Optional source location; `repositoryType` is required when a URL is given. |

`project`, `unlisted` and `deprecated` are the only package-level fields an existing entry may change.

A maintainer file (`sei-index.json`) has the same shape but no `upstream`, `maintainers`, or `source*` fields; those belong to the index side.

### Source overlay

Index maintainers can retire a version or add a finding without touching the maintainer's data:

- `sourceYanked: true` yanks a version; `sourceAdvisories` adds findings.
- `sourceUnlisted` and `sourceDeprecated` do the same at package level.
- The client merges the overlay into the standard fields, so an older client still honours it.

## catalog.json

`catalog.json` is generated from the mirrors and powers one-request search plus `--tag` and `--license`. Regenerate it with `sk index catalog .` after any change; CI fails when it is stale.

## Rules

- **Versions are immutable.** Append new versions; never edit an existing version entry or remove one.
- **Only `yanked`, `deprecated`, `advisory`, and the source overlay may change in an existing version.** Package-level `unlisted`, `deprecated`, and `project` may also change. `yanked: true` hides a version from new resolutions but keeps it available for lock replay; `deprecated` is a human-readable migration message; `advisory.severity: "critical"` blocks new resolutions unless the user passes `--allow-critical`.
- **Never delete a sei or a version.** Yanking, deprecating, or unlisting is the retirement path.
- **The `sei` list in `index.json` may only grow.** Removing a name breaks search and is rejected.
- **Artifacts must be zip archives** with exactly one root `sei.json` (the current store extracts zip only).
- **The index entry must match the embedded `sei.json`** for `schemaVersion`, `name`, `version`, all four relations at both scopes, `rid`, `layout`, and `modes`.
- **Checksums are exact.** `sha256` is 64 lowercase hex characters and `size` is the archive size in bytes; CI downloads every artifact and verifies both.

## Schema

`index.json`:

```json
{
  "schemaVersion": 2,
  "generatedBy": "SeiIndex maintainers",
  "sei": ["hello-seiko"]
}
```

`sei/hello-seiko.json`:

```json
{
  "schemaVersion": 2,
  "name": "hello-seiko",
  "project": {
    "description": "Example sei used in this README.",
    "authors": ["example"],
    "license": "MIT",
    "tags": ["example"],
    "repositoryUrl": "https://github.com/example/hello-seiko",
    "repositoryType": "git"
  },
  "unlisted": false,
  "deprecated": null,
  "versions": [
    {
      "version": "1.0.0",
      "dependencies": [
        { "name": "hosihikari", "version": "[1.1.0,1.2.0)" }
      ],
      "prerequisites": [],
      "optionalPeers": [],
      "conflicts": [],
      "artifacts": [
        {
          "rid": "win-x64",
          "dependencies": [],
          "prerequisites": [
            { "name": "hosihikari-hosting-levilamina", "version": "*" }
          ],
          "optionalPeers": [],
          "conflicts": [],
          "layout": "root",
          "source": {
            "url": "https://github.com/example/hello-seiko/releases/download/v1.0.0/hello-seiko-win-x64.zip",
            "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "size": 12345
          }
        }
      ],
      "yanked": false,
      "deprecated": null,
      "advisory": null
    }
  ]
}
```

The zip's root `sei.json` for that artifact:

```json
{
  "schemaVersion": 2,
  "name": "hello-seiko",
  "version": "1.0.0",
  "dependencies": [
    { "name": "hosihikari", "version": "[1.1.0,1.2.0)" }
  ],
  "prerequisites": [],
  "optionalPeers": [],
  "conflicts": [],
  "artifact": {
    "rid": "win-x64",
    "dependencies": [],
    "prerequisites": [
      { "name": "hosihikari-hosting-levilamina", "version": "*" }
    ],
    "optionalPeers": [],
    "conflicts": [],
    "layout": "root",
    "modes": { "hello-seiko": "0755" }
  }
}
```

Fields:

- `version` uses NuGet SemVer. Pre-releases are excluded unless the declaration asks for them.
- `dependencies[].version` is a NuGet version range; `null`, omitted, or `"*"` means any version.
- Relations are version-level at the version object and artifact-level inside the artifact object. `prerequisites` must already be in the graph and drive artifact selection; `optionalPeers` must match when present; `conflicts` excludes versions.
- `rid` matches the target platform, for example `win-x64` or `linux-arm64`. Omit `rid` for a platform-independent artifact.
- `layout` is `root` (or omitted). Other shapes are not supported yet.
- `modes` belongs to the embedded `sei.json` only; it sets Unix executable bits, for example `{ "sk": "0755" }`. Windows ignores it.
- `unlisted` belongs to the sei file: `true` hides the name from `sk search`; direct resolution and lock replay keep working.
- `deprecated` may be set per version or on the sei file. The package-level message is inherited by versions that do not set their own.
- `advisory` is `{ "severity": "low|moderate|high|critical", "url": "..." }`. A `critical` version is skipped by new resolution unless the user passes `--allow-critical`; lock replay is allowed and warns.

Every version needs at least one artifact, and two artifacts in one version cannot have identical `rid` and `prerequisites`.

## Maintainer-published indexes

A registered package is mirrored from a `sei-index.json` the maintainers publish in their own repository or site; the README rules above still apply, now to that file.

- **Register** with the *Register a sei* form (name + URL). A maintainer adds `register-approved`; the bot fetches, validates and opens the pull request.
- **Refresh** happens every six hours, or right away with the *Refresh a registered sei* form. Only the issue author's login must be in the package's `maintainers` list.
- **The mirror is append-only**: new versions are appended, `project` and retirement text may change, a rewritten or removed version fails the refresh and must ship as a new version.
- **Source overlay** is index-side: `sourceYanked`, `sourceAdvisories`, `sourceUnlisted`, `sourceDeprecated` live in the mirror and survive every refresh.
- **`upstream` and `maintainers` are index-side too**; a maintainer file must not declare them.

A maintainer file uses the same `SeiIndex` schema plus `project`, and nothing else index-side. Validate it locally with `sk index verify ./sei-index.json` before pushing.

## Release automation

`.github/actions/sei-release` is a composite action that writes `sei-index.json` from already-uploaded release artifacts: it reads each artifact's root `sei.json`, records URL, digest and size, reuses the version entry when the artifact is unchanged, and refuses to rewrite a published version. `.github/templates/release-sei.yml` is a starting workflow.

```yaml
- uses: Hosihikari/SeiIndex/.github/actions/sei-release@main
  with:
    index-path: sei-index.json
    artifacts: |
      [{ "rid": "win-x64", "path": "dist/hello.zip", "url": "https://github.com/you/repo/releases/download/v1.0.0/hello.zip" }]
```

The action runs with your repository's permissions and never touches this index; the refresh picks the file up afterwards.

## Verify locally

```bash
sk index verify . --check-artifacts --strict
sk index catalog . --check
```

The submission CI also runs `sk index verify` against a single `sei-index.json`; the file mode checks the same rules without needing the surrounding index.

The command prints findings and exits non-zero on errors (or on warnings with `--strict`). `--json` emits the usual Seiko envelope. CI runs the same command with a pinned `sk` version, plus `git diff` checks for the append-only rules. The 0.3 schema migration is a one-time exception to those rules; after it, versions are append-only again.
