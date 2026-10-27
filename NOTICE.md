# Third-party data and attribution

The MIT license applies to original tool code. It does not relicense third-party materials.

## Chain.Love catalog

Source: https://github.com/Chain-Love/chain-love

Snapshot: commit `09e5460c2e4697f6e0a4854f93e97efab5764c44`, `references/offers/sdks.csv`.

License: Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0), copied in `sources/chain-love/LICENSE.txt`.

- `sources/chain-love/sdks.csv` is an unchanged source snapshot.
- `examples/chain-love-npm.csv`, the Chain.Love rows in `examples/maintenance-pilot.csv`, and reports containing their expected values are derived subsets, under CC BY-SA 4.0 for that catalog data.
- Changes made here: selected records; added explicit registry mappings and audit configuration; normalized dependency order for comparison; supplied source observations, difference annotations, and research triage. No upstream catalog data was modified by the auditor.
- No endorsement by Chain.Love is implied.

## Registry metadata and project manifests

Raw responses in `artifacts/**/evidence/` and project manifests in `sources/mapping-review/` are supplied by their respective publishers. Retention demonstrates what was observed; it does not grant rights beyond applicable upstream licenses. Such responses may contain publicly published maintainer contact details. Reports do not need those contact fields and do not reproduce them in the rendered UI.

Official API reference URLs are recorded in the README. Project manifests are used only to corroborate package identity, never as a substitute for published-version dependency evidence.
