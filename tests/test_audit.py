import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evidence_ledger.audit import run_audit, verify_bundle
from evidence_ledger.cli import main
from evidence_ledger.model import InputError, sha256
from evidence_ledger.render import spreadsheet_safe
from evidence_ledger.transport import Response


def manifest_csv(rows):
    fields = [
        "record_id",
        "ecosystem",
        "package",
        "expected_version",
        "expected_dependencies",
        "expected_license",
        "dependency_scope",
    ]
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fields)
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode()


class FakeTransport:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        value = self.mapping[url]
        if isinstance(value, Response):
            return [value]
        return [
            Response(
                url,
                200,
                {"content-type": "application/json"},
                json.dumps(value).encode(),
                "2026-10-27T15:52:00Z",
                1,
            )
        ]


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.input = self.root / "packages.csv"
        self.out = self.root / "run"

    def tearDown(self):
        self.tmp.cleanup()

    def build(self):
        self.input.write_bytes(
            manifest_csv(
                [
                    {
                        "record_id": "drift",
                        "ecosystem": "npm",
                        "package": "one",
                        "expected_version": "0.9",
                    },
                    {
                        "record_id": "match",
                        "ecosystem": "npm",
                        "package": "one",
                        "expected_version": "1.0",
                    },
                    {"record_id": "observe", "ecosystem": "npm", "package": "one"},
                    {
                        "record_id": "empty-source",
                        "ecosystem": "npm",
                        "package": "two",
                        "expected_dependencies": "[]",
                    },
                    {
                        "record_id": "missing-field",
                        "ecosystem": "npm",
                        "package": "three",
                        "expected_license": "MIT",
                    },
                ]
            )
        )
        transport = FakeTransport(
            {
                "https://registry.npmjs.org/one/latest": {
                    "name": "one",
                    "version": "1.0",
                    "license": "MIT",
                },
                "https://registry.npmjs.org/two/latest": {},
                "https://registry.npmjs.org/three/latest": {"name": "three", "version": "2.0"},
            }
        )
        report = run_audit(self.input, self.out, transport)
        return report, transport

    def test_real_pipeline_all_states_dedup_and_offline_recompute(self):
        report, transport = self.build()
        self.assertEqual(
            report["summary"],
            {
                "changed": 1,
                "unchanged": 1,
                "observed": 1,
                "unavailable": 2,
                "total": 5,
                "compared": 4,
                "differences": 1,
            },
        )
        self.assertEqual(len(transport.calls), 3)
        with patch(
            "urllib.request.OpenerDirector.open",
            side_effect=AssertionError("offline verification attempted network"),
        ):
            result = verify_bundle(self.out)
        self.assertTrue(result["ok"])
        self.assertEqual(result["records_verified"], 5)
        self.assertTrue((self.out / "report.html").exists())
        self.assertTrue((self.out / "corrections.csv").exists())

    def test_no_overwrite(self):
        self.build()
        with self.assertRaisesRegex(InputError, "already exists"):
            run_audit(self.input, self.out, FakeTransport({}))

    def test_failure_does_not_publish_partial_bundle(self):
        self.input.write_bytes(
            manifest_csv([{"record_id": "one", "ecosystem": "npm", "package": "one"}])
        )
        with self.assertRaises(KeyError):
            run_audit(self.input, self.out, FakeTransport({}))
        self.assertFalse(self.out.exists())
        self.assertFalse(list(self.root.glob(".evidence-ledger-*")))

    def test_tamper_body_detected(self):
        self.build()
        body = next((self.out / "evidence").glob("*.json"))
        body.write_text("tampered")
        with self.assertRaisesRegex(InputError, "integrity failure"):
            verify_bundle(self.out)

    def test_tamper_report_detected(self):
        self.build()
        report = self.out / "report.json"
        report.write_text(report.read_text() + " ")
        with self.assertRaisesRegex(InputError, "integrity failure"):
            verify_bundle(self.out)

    def test_rehashing_false_summary_does_not_bypass_semantic_recompute(self):
        self.build()
        p = self.out / "report.json"
        d = json.loads(p.read_text())
        d["summary"]["unavailable"] = 0
        p.write_text(json.dumps(d))
        m = self.out / "manifest.json"
        data = json.loads(m.read_text())
        data["files"]["report.json"] = sha256(p.read_bytes())
        m.write_text(json.dumps(data))
        with self.assertRaisesRegex(InputError, "summary"):
            verify_bundle(self.out)

    def test_rehashing_false_result_does_not_bypass_semantic_recompute(self):
        self.build()
        p = self.out / "report.json"
        d = json.loads(p.read_text())
        d["results"][0]["state"] = "unchanged"
        p.write_text(json.dumps(d))
        m = self.out / "manifest.json"
        data = json.loads(m.read_text())
        data["files"]["report.json"] = sha256(p.read_bytes())
        m.write_text(json.dumps(data))
        with self.assertRaisesRegex(InputError, "recomputed result differs"):
            verify_bundle(self.out)

    def test_rehashing_html_injection_still_fails_export_recompute(self):
        self.build()
        p = self.out / "report.html"
        p.write_text(p.read_text() + "<script>alert(1)</script>")
        m = self.out / "manifest.json"
        data = json.loads(m.read_text())
        data["files"]["report.html"] = sha256(p.read_bytes())
        m.write_text(json.dumps(data))
        with self.assertRaisesRegex(InputError, "recomputed export differs"):
            verify_bundle(self.out)

    def test_unlisted_file_rejected(self):
        self.build()
        (self.out / "unlisted.txt").write_text("surprise")
        with self.assertRaisesRegex(InputError, "file list"):
            verify_bundle(self.out)

    def test_manifest_cannot_omit_html(self):
        self.build()
        m = self.out / "manifest.json"
        data = json.loads(m.read_text())
        del data["files"]["report.html"]
        m.write_text(json.dumps(data))
        with self.assertRaisesRegex(InputError, "missing generated"):
            verify_bundle(self.out)

    def test_unsafe_path_and_symlink_rejected(self):
        self.build()
        m = self.out / "manifest.json"
        data = json.loads(m.read_text())
        data["files"]["../outside"] = sha256(b"no")
        m.write_text(json.dumps(data))
        with self.assertRaisesRegex(InputError, "unsafe"):
            verify_bundle(self.out)

    def test_html_script_breakout_is_escaped_and_csp_present(self):
        self.input.write_bytes(
            manifest_csv(
                [
                    {
                        "record_id": "</script><img src=x onerror=alert(1)>",
                        "ecosystem": "npm",
                        "package": "one",
                    }
                ]
            )
        )
        run_audit(
            self.input,
            self.out,
            FakeTransport(
                {"https://registry.npmjs.org/one/latest": {"name": "one", "version": "1"}}
            ),
        )
        text = (self.out / "report.html").read_text()
        self.assertNotIn("</script><img", text)
        self.assertIn("\\u003c/script", text)
        self.assertIn("Content-Security-Policy", text)
        self.assertIn("script-src &#x27;sha256-", text)

    def test_csv_formula_prefix_guard(self):
        for value in [
            "=HYPERLINK('evil')",
            "+cmd",
            "-1",
            "@scope/name",
            " \t=1+1",
            "\tstuff",
            "\rtext",
        ]:
            self.assertTrue(spreadsheet_safe(value).startswith("'"))
        self.assertEqual(spreadsheet_safe("ordinary"), "ordinary")

    def test_cli_error_status_and_verify(self):
        self.build()
        with patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(main(["verify", str(self.out)]), 0)
        with patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(main(["audit", str(self.input), "--out", str(self.out)]), 3)


if __name__ == "__main__":
    unittest.main()
