import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_audit import FakeTransport, manifest_csv

from evidence_ledger.history import compare_reports, watch
from evidence_ledger.model import InputError


def result(ident="one", state="unchanged", version="1"):
    return {
        "record": {
            "record_id": ident,
            "package": "one",
            "ecosystem": "npm",
            "selector": "latest",
            "expected": {"version": "1"},
            "dependency_scope": "runtime+peer",
            "source_ref": "",
        },
        "state": state,
        "error": "timeout" if state == "unavailable" else None,
        "observed": None
        if state == "unavailable"
        else {"version": version, "license": "MIT", "dependencies": []},
    }


def report(*results):
    return {"finished_at": "2026-01-01T00:00:00Z", "results": list(results)}


class DeltaTests(unittest.TestCase):
    def test_unchanged_requires_both_verified_observations(self):
        old = report(result())
        new = report(result())
        self.assertEqual(compare_reports(old, new)["summary"], {"unchanged_verified": 1})
        new = report(result(state="unavailable"))
        self.assertEqual(compare_reports(old, new)["summary"], {"unavailable": 1})
        self.assertEqual(compare_reports(new, old)["summary"], {"recovered": 1})
        self.assertEqual(compare_reports(new, new)["summary"], {"unavailable": 1})

    def test_changes_are_field_specific(self):
        delta = compare_reports(report(result()), report(result(state="changed", version="2")))
        self.assertEqual(delta["summary"], {"source_changed": 1})
        self.assertEqual(
            delta["results"][0]["changes"], [{"field": "version", "before": "1", "after": "2"}]
        )

    def test_catalog_assertion_changes_are_not_registry_changes(self):
        old = report(result())
        new = copy.deepcopy(old)
        new["results"][0]["record"]["expected"]["version"] = "2"
        self.assertEqual(compare_reports(old, new)["summary"], {"configuration_changed": 1})

    def test_added_removed_records_are_not_source_changes(self):
        delta = compare_reports(report(result("old")), report(result("new")))
        self.assertEqual(delta["summary"], {"record_added": 1, "record_removed": 1})

    def test_watch_single_live_round_then_stops_and_freezes_input(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "input.csv"
            out = base / "history"
            original = manifest_csv([{"record_id": "one", "ecosystem": "npm", "package": "one"}])
            source.write_bytes(original)
            transport = FakeTransport(
                {"https://registry.npmjs.org/one/latest": {"name": "one", "version": "1"}}
            )
            clock = [0.0]

            def advance(seconds):
                clock[0] += seconds

            with (
                patch("evidence_ledger.history.time.monotonic", side_effect=lambda: clock[0]),
                patch("evidence_ledger.history.time.sleep", side_effect=advance),
            ):
                index = watch(source, out, duration=1, interval=60, transport=transport)
            self.assertEqual(index["status"], "finished")
            self.assertEqual(len(index["runs"]), 1)
            self.assertEqual((out / "watch-input.csv").read_bytes(), original)
            self.assertEqual(json.loads((out / "history.json").read_text())["status"], "finished")
            self.assertIn("巡检已结束", (out / "index.html").read_text())
            with self.assertRaises(InputError):
                watch(source, out, 1, 60, transport)

    def test_watch_two_rounds_write_delta_without_silent_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "input.csv"
            out = base / "history"
            source.write_bytes(
                manifest_csv([{"record_id": "one", "ecosystem": "npm", "package": "one"}])
            )
            transport = FakeTransport(
                {"https://registry.npmjs.org/one/latest": {"name": "one", "version": "1"}}
            )
            clock = [0.0]

            def advance(seconds):
                clock[0] += seconds

            with (
                patch("evidence_ledger.history.time.monotonic", side_effect=lambda: clock[0]),
                patch("evidence_ledger.history.time.sleep", side_effect=advance),
            ):
                index = watch(source, out, 61, 60, transport)
            self.assertEqual(len(index["runs"]), 2)
            self.assertEqual(index["runs"][1]["delta_summary"], {"unchanged_verified": 1})
            self.assertTrue((out / "run-002-delta.json").exists())

    def test_watch_invalid_interval_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "input.csv"
            out = Path(temp) / "out"
            for duration, interval in [(0, 60), (1, 1), (90000, 60)]:
                with self.assertRaises(InputError):
                    watch(source, out, duration, interval)
            self.assertFalse(out.exists())

    def test_interruption_is_recorded_and_not_claimed_finished(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "input.csv"
            out = Path(temp) / "out"
            source.write_bytes(
                manifest_csv([{"record_id": "one", "ecosystem": "npm", "package": "one"}])
            )
            transport = FakeTransport(
                {"https://registry.npmjs.org/one/latest": {"name": "one", "version": "1"}}
            )
            with (
                patch("evidence_ledger.history.time.sleep", side_effect=KeyboardInterrupt),
                self.assertRaises(KeyboardInterrupt),
            ):
                watch(source, out, 61, 60, transport)
            self.assertEqual(
                json.loads((out / "history.json").read_text())["status"], "interrupted"
            )



class HistoryIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / "input.csv"
        self.output = self.root / "history"
        self.input.write_bytes(
            manifest_csv(
                [
                    {"record_id": "one", "ecosystem": "npm", "package": "one"},
                    {
                        "record_id": "same-package-other-record",
                        "ecosystem": "npm",
                        "package": "one",
                    },
                ]
            )
        )
        transport = FakeTransport(
            {"https://registry.npmjs.org/one/latest": {"name": "one", "version": "1"}}
        )
        clock = [0.0]

        def advance(seconds):
            clock[0] += seconds

        with (
            patch("evidence_ledger.history.time.monotonic", side_effect=lambda: clock[0]),
            patch("evidence_ledger.history.time.sleep", side_effect=advance),
        ):
            watch(self.input, self.output, 61, 60, transport)

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_history_seal_and_counts_do_not_inflate_package_coverage(self):
        from evidence_ledger.history import seal_history, verify_history

        result = verify_history(self.output)
        self.assertEqual(result["completed_rounds_verified"], 2)
        self.assertEqual(result["unique_input_records"], 2)
        self.assertEqual(result["unique_package_queries_per_round"], 1)
        self.assertEqual(result["record_observations_verified"], 4)
        self.assertFalse(result["sealed"])
        self.assertTrue(seal_history(self.output)["sealed"])
        with self.assertRaisesRegex(InputError, "already sealed"):
            seal_history(self.output)

    def test_delta_tamper_is_detected(self):
        from evidence_ledger.history import verify_history

        (self.output / "run-002-delta.json").write_text("{}")
        with self.assertRaisesRegex(InputError, "delta mismatch"):
            verify_history(self.output)

    def test_running_history_is_not_claimed_finished_or_sealable(self):
        from evidence_ledger.history import seal_history, verify_history

        path = self.output / "history.json"
        data = json.loads(path.read_text())
        data["status"] = "running"
        path.write_text(json.dumps(data))
        self.assertEqual(verify_history(self.output)["status"], "running")
        with self.assertRaisesRegex(InputError, "running history"):
            seal_history(self.output)

    def test_sealed_history_hash_links_are_checked(self):
        from evidence_ledger.history import seal_history, verify_history

        seal_history(self.output)
        path = self.output / "history-manifest.json"
        data = json.loads(path.read_text())
        data["files"]["history.json"] = "0" * 64
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(InputError, "seal hash mismatch"):
            verify_history(self.output)


if __name__ == "__main__":
    unittest.main()
