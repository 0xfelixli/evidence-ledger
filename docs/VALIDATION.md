# Validation record

This file records performed checks, not future guarantees.

## Automated reliability tests

At 2026-10-27 16:05 UTC, 53 unittest methods passed on the host Python 3.9.6. The suite includes:

- malformed/empty CSV, duplicate identities, scoped npm and normalized PyPI names, path/query/control-character rejection;
- JSON dependency assertions and the difference between blank (no assertion) and `[]` (assertion of none);
- source name/version mismatch, empty success envelopes, absent expected fields, and partial unknown observations;
- JSON MIME/decoding/duplicate-key errors, body limits, HTTP errors, retries, and mid-response disconnects;
- HTML script-breakout escaping, a script-hash CSP, and spreadsheet formula-prefix guards;
- evidence, result, summary and export tampering, including a false result whose manifest has been rehashed;
- no partial bundle publication, no destination overwrite, source deduplication, deterministic offline recomputation with network explicitly blocked;
- source changes vs configuration changes, unavailable vs recovered, bounded monitoring, frozen inputs, and interruption status.

Command: `PYTHONPATH=src python3 -m unittest discover -s tests -v`.

## Live registry runs

- `artifacts/catalog-reviewed`: 24 npm catalog records, 14 changed / 10 unchanged / 0 unavailable; all saved sources and exports verify.
- `artifacts/quickstart`: 4 observation-only records across npm and PyPI; these are not counted as compared or passed assertions.
- `artifacts/catalog-first`: a development run with one incorrect package mapping; retained transparently, not presented as a real service outage. Its HTML exports were regenerated during development to correct canonical serialization; raw responses were preserved.
- `artifacts/maintenance-pilot`: bounded foreground monitoring. Actual completion/status/counts must be read from `history.json`; no future samples are claimed in this document.

## Browser checks performed

Using Ego Lite Chromium and actual report files:

- Desktop report renders all 24 records and counts.
- State filter + search for `iso-filecoin-react` produces exactly one row.
- Expanding that row displays the original/current arrays, additions/removals, source timestamp and SHA-256.
- The filtered CSV download was actually saved and parsed; it contains one data record, not the whole unfiltered dataset.
- At a 390 × 844 viewport, document width is 390 CSS px (no horizontal document overflow); screenshot inspected.

Screenshots and downloaded CSV: `artifacts/qa/`.

## Limits

No paid transaction, upstream merge, vulnerability audit, installed-package test, license legal review, or human reviewer acceptance is asserted. Socket timeout is not a hard total request deadline. A valid publisher response can still contain inaccurate publisher metadata. Integrity hashes detect internal inconsistency, not a coordinated forgery of the whole bundle.

## Workbench and packaging follow-up

- The suite reached 73 passing methods on Python 3.9.6, including loopback-only HTTP endpoints, Origin/Host/CSRF rejection, queue limits, bad input and real bundle generation, history seals, frozen input and independent package-vs-record counts.
- Ruff checks pass with an explicit Python 3.9 target.
- A branch-coverage run before the four history-integrity tests measured 87% overall (not 100%, and not a claim of exhaustive security testing).
- A wheel was built and installed into a fresh virtual environment with `--no-index --no-deps`. Its CLI reports 0.1.0 and independently verifies the saved 24-record real case.
- Browser workbench: a real two-package npm/PyPI observation-only job completed, then the 24-record catalog example completed in 5.32 seconds with 14 changed / 10 unchanged / 0 unavailable. An invalid path-like package name produced an error and did not create another job.
- A 10,000-row **synthetic repeated-record** benchmark used one saved source and zero network requests: generation with tracemalloc 2.271 s, offline verification 1.814 s, peak traced Python allocation 199,467,909 bytes. It is not evidence of 10,000 unique package audits.
- Its browser report rendered 50 records per page; measured navigation duration was 81 ms on this host Chromium run. Filtering to 100 records and visiting page 2 still exported all 100 matching records, not only the visible page. Raw measurements and CSV are in `artifacts/`.
- The published source at commit `7b95b06eb79689df6b39af54358668a9d59cda61` was downloaded independently from GitHub: all 98 file contents matched the staging tree, its 73 tests passed on the host, and its saved real case verified from outside the project directory. Receipt: `artifacts/public-download-receipt.json` in the local handover.
- GitHub Actions [run #1](https://github.com/0xfelixli/evidence-ledger/actions/runs/40544669722) completed successfully across the Python 3.9 / 3.11 / 3.13 matrix on Linux (24 seconds overall). The UI reported action Node-runtime migration warnings; these did not cause test failures. This is CI evidence for these three environments, not a claim about all Python versions.

## Offline verifier hardening (17:00–17:08 UTC)

Adversarial review reproduced three accepted/uncaught cases: an unlisted nested file named `manifest.json`, a root manifest that was a symlink, and malformed result structures escaping as `AttributeError`. A separately re-rendered and rehashed report could also overstate its unique-source count. The verifier now rejects these inputs, inventories regular files before content reads, rejects special files, uses bounded strict control JSON (duplicate keys, non-finite numbers and extreme nesting rejected), validates receipt structure and recomputes distinct source counts. Generation applies matching file-size limits before publishing a bundle.

The suite reached **82 passing methods** locally; the newly added cases include a POSIX FIFO rejected before reading, duplicate/non-finite control documents, malformed receipts, and malformed history rounds. Existing real saved bundles and the five completed pilot rounds still verify. This does not create a digital signature or prove historical collection authenticity.

The workflow action references were refreshed against their [official checkout](https://github.com/actions/checkout), [setup-python](https://github.com/actions/setup-python) and [upload-artifact](https://github.com/actions/upload-artifact) documentation and pinned to the resolved v7 commit hashes. The manual cloud audit is explicitly on-demand, with seven-day artifact retention; execution results will be recorded after an actual run.

## Cloud execution and distributable verification

- The hardened code at `9021b1eb1cdb5b9808a6b84dda7388dae47336b3` passed the [82-test Linux matrix](https://github.com/0xfelixli/evidence-ledger/actions/runs/40548828613).
- The on-demand [cloud audit run](https://github.com/0xfelixli/evidence-ledger/actions/runs/40549079384) actually queried the 24-record public input at 17:17 UTC and completed successfully. Its artifact `public-catalog-evidence-40549079384` was downloaded through the browser; its ZIP SHA-256 matched GitHub's displayed `3db02c88af068e90441efce5b3c0494951758983ffc37cafaaa3d26c7c67334b`. Local offline verification passed (24 records, 29 manifest-listed files). Comparison to the first local case found 24 unchanged compared field sets. No unobserved later runs are implied.
- The rebuilt wheel was installed with `--no-index --no-deps` in an isolated virtual environment. From `/tmp`, the installed package (not the working source tree) passed all 82 tests and verified the saved real case. The sdist now explicitly includes examples, documentation, source attribution and saved case evidence; its contents were inspected for expected paths, executable launcher mode, excluded local work directories and credential-like material.
- The workbench's actual file picker rejected malformed UTF-8 with its Run button disabled, then accepted a valid quickstart CSV and re-enabled it.
- The static landing page was visually inspected on desktop and at 390 px width without horizontal overflow. GitHub Pages was tried but inherited the owner's existing blog domain, whose project path returned 404; this repository's Pages setting was restored to disabled. The included landing/report files work locally; no live demo hosting claim is made.

## Portable handover builder

The release builder accepts an explicitly supplied sdist/wheel and an ended, sealed history. It packages no arbitrary working-directory tree, preserves launcher modes, computes distribution checksums, then extracts its own portable ZIP and re-verifies the bundled case/history/cloud reports. A real one-round, four-package quickstart history was used for an initial packaging smoke test; this is a packaging check, not the long-running pilot or four hours of observations. The final long-running pilot remains separate until its actual stop time.
