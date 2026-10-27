# Evidence Ledger

[中文说明](README.md) · [Source](https://github.com/0xfelixli/evidence-ledger)

A read-only auditor for software catalogs. Compare CSV assertions with publisher metadata from npm and PyPI; retain the response bytes and produce an offline HTML report, review CSV and evidence manifest.

The tool does not install or execute packages. A metadata mismatch is a review candidate, not a vulnerability finding or proof that a catalog must follow the latest version.

## Try the saved case first

Download and extract this repository, then open `index.html` or `artifacts/catalog-reviewed/report.html` in a browser. The saved case checks **24 records** from a fixed Chain.Love catalog commit: **14 dependency-declaration mismatches, 10 matches, zero unavailable sources** at the recorded collection time. The [case study](docs/CASE-STUDY.zh-CN.md) explains optional peers, existing upstream proposals and why these are not 14 automatically actionable fixes.

With Python 3.9+ on macOS or Linux:

```sh
python3 run.py verify artifacts/catalog-reviewed
python3 run.py audit examples/quickstart.csv --out runs/first-check
python3 run.py verify runs/first-check
```

No pip installation or runtime third-party dependency is needed. The host was tested on macOS/Python 3.9.6; the public Linux CI matrix covers Python 3.9, 3.11 and 3.13. Windows has not been validated. A wheel can also be installed into your own virtual environment; the entry point is `evidence-ledger`.

## Run from a local browser

```sh
python3 run.py serve --out runs/workbench --example examples/chain-love-npm.csv --open
```

Upload or paste a UTF-8 CSV, run the audit, and open its saved report. The UI is in Chinese; CSV/JSON field names and state codes are English. It listens only on `127.0.0.1` with a random port, same-origin checks and a session token. The browser interface limits each batch to 2 MiB / 500 records. Stop its foreground process with Ctrl-C; saved reports remain on disk.

## Describe what you want checked

The required CSV columns are `record_id`, `ecosystem` and `package`. IDs must be unique. Ecosystems are `npm` and `pypi`.

```csv
record_id,ecosystem,package,selector,expected_version
requests-current,pypi,requests,latest,
requests-pinned,pypi,requests,2.34.2,2.34.2
```

This is an input-shape example, not an assertion that this pinned version is currently the latest or suitable for your application. A blank assertion means observation only. `expected_dependencies` accepts a JSON string array; a blank cell means no dependency assertion, while `[]` explicitly asserts none. The remaining optional assertion columns are `expected_license` and `expected_repository`.

- `selector`: `latest` (default) or a pinned version; ranges and arbitrary distribution tags are rejected.
- `dependency_scope`: npm declaration groups `runtime`, `runtime+peer` (default), or `runtime+peer+optional`. No development or transitive dependencies are resolved. Optional peers remain peer declarations.
- `source_ref`: your catalog provenance/reference, retained locally. Only package names and selectors are sent to the registries.

PyPI requirements retain markers/extras verbatim. License values are publisher declarations; this tool does not validate SPDX semantics or inspect license files. Repository links are normalized conservatively, without guessing that a project home page is its source repository.

## Read the result correctly

| State | Meaning |
|---|---|
| `changed` | At least one supplied assertion differs from observed metadata. |
| `unchanged` | All supplied assertions match the observed fields. |
| `observed` | Metadata was collected, but no catalog assertions were supplied. |
| `unavailable` | Source retrieval/validation failed, or an asserted field could not be established. |

Partially unknown records retain any known differences and still count as unavailable. Malformed or empty success envelopes cannot silently become a clean pass.

Each new output directory contains `input.csv`, `report.json`, `report.html`, `review.csv`, `corrections.csv`, `manifest.json`, and content-addressed raw bodies under `evidence/`. Existing destinations are never reused. Reports support search, state filters and filtered CSV export. Exports guard common spreadsheet-formula prefixes; use JSON for exact original values.

Complete files are staged on the same filesystem, then published by renaming over an empty directory reservation. SIGKILL can leave an orphan `.evidence-ledger-*` staging directory or an empty reserved destination; neither is a successful report, and `verify` rejects the empty destination. Use a fresh output path to rerun. This protocol is not a power-loss durability guarantee; no disk or power-failure test was performed.

## Verify and monitor

`verify` runs completely offline: it checks inventory/hashes, input identity, receipt structure, source normalization, counts, and regenerated HTML/CSV content. It rejects symlinks, special files, ambiguous control JSON and oversized files. A manifest provides internal consistency, not a digital signature, authentic historical timestamp or protection against a coordinated rewrite of the whole bundle.

```sh
python3 run.py watch examples/maintenance-pilot.csv --out runs/one-hour \
  --duration 3600 --interval 900
python3 run.py verify-history runs/one-hour
python3 run.py seal-history runs/one-hour
python3 run.py diff runs/day-one runs/day-two > changes.json
```

Monitoring freezes its input, samples immediately, skips missed slots and has an explicit stop time. It is a bounded foreground process. An unexpected process exit may leave a `running` index; check its last-update time. A request already in progress can finish after the stop time. Socket timeouts are not hard whole-run deadlines.

Snapshot deltas distinguish source changes, verified unchanged fields, failures, recovery, configuration changes, and added/removed records. Compared source fields are version, declared license, repository/directory, selected dependency strings and npm deprecation text. Other raw metadata changes—including peer optionality, dependency-group moves and PyPI yank status—require separate review of the saved responses.

For an on-demand cloud run, use repository **Actions → manual-public-catalog-audit → Run workflow**. This fixed public 24-record example produces a downloadable evidence artifact with seven-day retention. It has no schedule. The first real [cloud run](https://github.com/0xfelixli/evidence-ledger/actions/runs/40549079384) completed and its downloaded artifact was independently verified locally. Repository write/Actions permission is needed to trigger a run.

## Operational bounds

Requests use HTTPS to `registry.npmjs.org` and `pypi.org` only, with no ambient proxy, cookies or account credentials, and no redirects. Defaults: four concurrent requests and one short retry. CLI limits: 8 MiB / 10,000 input records, 16 MiB per source response, 256 MiB of archived source bytes, 64 MiB estimated normalized results, 256 MiB per generated/verified file, and an 8 MiB manifest. Split large workloads into smaller batches.

Exit codes: `0` completed, `1` differences with `--fail-on-change`, `2` unavailable observations, `3` input/file/configuration error, `130` interrupted. Differences do not fail a normal audit. The manual cloud workflow attempts artifact verification/upload even when some observations are unavailable; inspect the report's actual states.

## Tests and license

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

For an offline distinct-source stress check, run `python3 tools/benchmark_distinct.py --records 2000 --out runs/synthetic-distinct`. DNS and connection creation are blocked; generated identities and injected failures are synthetic, not real package research.

See [performed validation](docs/VALIDATION.md). Tests cover failure injection, wrong identities, malformed sources, output tampering, offline recomputation, interrupted monitoring, local HTTP boundaries and malformed evidence bundles. The saved case and cloud run are actual observations; the 10,000-row performance benchmark is explicitly synthetic repeated input, not 10,000 independent package checks.

Original code: MIT. Chain.Love catalog data, derived assertions and corresponding report data retain **CC BY-SA 4.0** attribution/share-alike terms. Publisher metadata rights remain with the respective owners; see [NOTICE](NOTICE.md). This is AI-assisted original work. No customer acceptance, upstream merge or earnings are asserted.
