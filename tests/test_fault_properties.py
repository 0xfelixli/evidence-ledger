"""Deterministic generated fault cases: accepted results must serialize safely."""

import copy
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_audit import FakeTransport, manifest_csv
from test_registry import NPM, PYPI

from evidence_ledger.audit import run_audit
from evidence_ledger.model import InputError, Record, SourceError, parse_csv
from evidence_ledger.registry import normalize
from evidence_ledger.transport import Response, parse_response


class FaultPropertyTests(unittest.TestCase):
    def test_unpaired_unicode_cannot_break_whole_batch_export(self):
        response = Response(
            "https://registry.npmjs.org/one/latest",
            200,
            {"content-type": "application/json"},
            b'{"name":"one","version":"1","license":"\\ud800"}',
            "2026-01-01T00:00:00Z",
            1,
        )
        with self.assertRaises(SourceError):
            parse_response(response)
        raw = manifest_csv(
            [
                {
                    "record_id": "one",
                    "ecosystem": "npm",
                    "package": "one",
                    "expected_dependencies": '["\\ud800"]',
                }
            ]
        )
        with self.assertRaisesRegex(InputError, "surrogate"):
            parse_csv(raw)

    def test_malformed_repository_is_row_failure_not_parser_crash(self):
        data = copy.deepcopy(NPM)
        data["repository"] = "https://["
        with self.assertRaises(SourceError):
            normalize(data, Record("one", "npm", "@scope/example"))
        data = copy.deepcopy(PYPI)
        data["info"]["project_urls"] = {"Source": "https://["}
        with self.assertRaises(SourceError):
            normalize(data, Record("one", "pypi", "some-package", dependency_scope="requires-dist"))

    def test_empty_wrong_type_is_not_silently_treated_as_missing(self):
        for value in [[], False, 0, ""]:
            data = copy.deepcopy(PYPI)
            data["info"]["project_urls"] = value
            with self.subTest(value=value), self.assertRaises(SourceError):
                normalize(
                    data, Record("one", "pypi", "some-package", dependency_scope="requires-dist")
                )

    def test_generated_shape_mutations_never_escape_as_unexpected_exceptions(self):
        rng = random.Random(20261027)
        values = [
            None,
            False,
            True,
            0,
            1,
            "",
            [],
            {},
            [1],
            {"wrong": []},
            "https://[",
            "</script>",
            {"url": 0},
            {"url": "https://["},
        ]
        rec = Record("one", "npm", "@scope/example")
        fields = [
            "name",
            "version",
            "dependencies",
            "peerDependencies",
            "optionalDependencies",
            "license",
            "repository",
            "deprecated",
        ]
        accepted = 0
        for i in range(1000):
            data = copy.deepcopy(NPM)
            data[rng.choice(fields)] = copy.deepcopy(rng.choice(values))
            try:
                observed = normalize(data, rec)
                json.dumps(observed, ensure_ascii=False, allow_nan=False).encode("utf-8")
                accepted += 1
            except SourceError:
                pass
        self.assertGreater(accepted, 0)

    def test_archive_budget_stops_run_without_false_green_or_partial_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.csv"
            out = root / "out"
            source.write_bytes(
                manifest_csv([{"record_id": "one", "ecosystem": "npm", "package": "one"}])
            )
            fake = FakeTransport(
                {"https://registry.npmjs.org/one/latest": {"name": "one", "version": "1"}}
            )
            with (
                patch("evidence_ledger.audit.MAX_ARCHIVE_BYTES", 10),
                self.assertRaisesRegex(InputError, "evidence exceeds"),
            ):
                run_audit(source, out, fake)
            self.assertFalse(out.exists())
            self.assertFalse(list(root.glob(".evidence-ledger-*")))

    def test_normalized_result_budget_stops_before_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.csv"
            out = root / "out"
            source.write_bytes(
                manifest_csv([{"record_id": "one", "ecosystem": "npm", "package": "one"}])
            )
            fake = FakeTransport(
                {"https://registry.npmjs.org/one/latest": {"name": "one", "version": "1"}}
            )
            with (
                patch("evidence_ledger.audit.MAX_RESULT_BYTES", 10),
                self.assertRaisesRegex(InputError, "results exceed"),
            ):
                run_audit(source, out, fake)
            self.assertFalse(out.exists())

    def test_strict_csv_rejects_trailing_quoted_garbage(self):
        with self.assertRaises(InputError):
            parse_csv(b'record_id,ecosystem,package\na,npm,"one"garbage\n')


if __name__ == "__main__":
    unittest.main()
