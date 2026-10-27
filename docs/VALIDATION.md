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
- A GitHub Actions matrix is supplied but has not been claimed to have run. Host tests cover Python 3.9.6; no other Python runtime result is invented.
