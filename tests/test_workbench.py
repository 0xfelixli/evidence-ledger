import http.client
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_audit import FakeTransport, manifest_csv

from evidence_ledger.audit import verify_bundle
from evidence_ledger.workbench import create_server


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.csv = manifest_csv(
            [{"record_id": "one", "ecosystem": "npm", "package": "one", "expected_version": "0"}]
        )
        self.example = self.root / "example.csv"
        self.example.write_bytes(self.csv)
        self.transport = FakeTransport(
            {"https://registry.npmjs.org/one/latest": {"name": "one", "version": "1"}}
        )
        self.server = create_server(
            self.root / "runs", transport=self.transport, example_path=self.example
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.origin = "http://127.0.0.1:" + str(self.port)
        _, _, body = self.request("GET", "/")
        self.token = re.search(r'name="csrf-token" content="([^"]+)"', body.decode()).group(1)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.manager.close()
        self.thread.join(2)
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body, headers or {})
        response = conn.getresponse()
        raw = response.read()
        out = (response.status, dict(response.getheaders()), raw)
        conn.close()
        return out

    def submit(self, csv=None, headers=None):
        base = {
            "Content-Type": "application/json",
            "Origin": self.origin,
            "X-Ledger-CSRF": self.token,
        }
        if headers:
            base.update(headers)
        return self.request(
            "POST", "/api/jobs", json.dumps({"csv": (csv or self.csv).decode()}), base
        )

    def wait_job(self, ident):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            _, _, raw = self.request("GET", "/api/jobs/" + ident)
            job = json.loads(raw)
            if job["status"] in {"completed", "failed"}:
                return job
            time.sleep(0.01)
        self.fail("job did not finish")

    def test_loopback_home_csp_and_no_credentials(self):
        status, headers, raw = self.request("GET", "/")
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn(b"script-src 'sha256-", raw)
        self.assertNotIn(b"api_key", raw)

    def test_invalid_host_cross_origin_and_missing_token_rejected(self):
        status, _, _ = self.request("GET", "/", headers={"Host": "evil.test"})
        self.assertEqual(status, 403)
        for headers in [
            {"Origin": "https://evil.test"},
            {"X-Ledger-CSRF": ""},
            {"X-Ledger-CSRF": "\xff"},
            {"Sec-Fetch-Site": "cross-site"},
        ]:
            with self.subTest(headers=headers):
                self.assertEqual(self.submit(headers=headers)[0], 403)
        self.assertEqual(self.server.manager.all(), [])

    def test_full_job_flow_and_saved_bundle_verify(self):
        status, _, raw = self.submit()
        self.assertEqual(status, 202)
        ident = json.loads(raw)["id"]
        job = self.wait_job(ident)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["summary"]["changed"], 1)
        status, headers, body = self.request("GET", job["report_url"])
        self.assertEqual(status, 200)
        self.assertIn(b"Evidence Ledger", body)
        self.assertTrue(verify_bundle(self.root / "runs" / ident / "report")["ok"])
        self.assertNotIn(self.token, (self.root / "runs" / ident / "job.json").read_text())

    def test_empty_success_source_remains_unavailable_in_web(self):
        self.transport.mapping["https://registry.npmjs.org/one/latest"] = {}
        _, _, raw = self.submit()
        job = self.wait_job(json.loads(raw)["id"])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["summary"]["unavailable"], 1)
        self.assertEqual(job["summary"]["unchanged"], 0)

    def test_bad_csv_never_queues_job(self):
        status, _, raw = self.submit(b"record_id,ecosystem,package\na,npm,../evil\n")
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(raw))
        self.assertEqual(self.server.manager.all(), [])

    def test_unknown_job_and_traversal_do_not_expose_files(self):
        for path in [
            "/api/jobs/" + "0" * 32,
            "/runs/" + "0" * 32 + "/report.html",
            "/runs/" + "0" * 32 + "/../../example.csv",
            "/api/jobs?other=1",
            "/example.csv",
        ]:
            with self.subTest(path=path):
                self.assertIn(self.request("GET", path)[0], {400, 404})

    def test_example_exact_data_and_no_global_filesystem_read(self):
        status, _, raw = self.request("GET", "/api/example")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["csv"].encode(), self.csv)
        self.assertEqual(self.request("GET", "/api/example?path=/etc/passwd")[0], 400)

    def test_body_type_and_over_limit_are_rejected(self):
        base = {"Origin": self.origin, "X-Ledger-CSRF": self.token}
        self.assertEqual(
            self.request("POST", "/api/jobs", "x", {**base, "Content-Type": "text/plain"})[0], 415
        )
        self.assertEqual(
            self.request("POST", "/api/jobs", "[]", {**base, "Content-Type": "application/json"})[
                0
            ],
            400,
        )
        many = manifest_csv(
            [{"record_id": str(i), "ecosystem": "npm", "package": "one"} for i in range(501)]
        )
        self.assertEqual(self.submit(many)[0], 400)

    def test_no_more_than_three_pending_jobs(self):
        gate = threading.Event()
        original = self.transport.get

        def blocked(url):
            gate.wait(2)
            return original(url)

        with patch.object(self.transport, "get", side_effect=blocked):
            for _ in range(3):
                self.assertEqual(self.submit()[0], 202)
            self.assertEqual(self.submit()[0], 400)
            gate.set()


if __name__ == "__main__":
    unittest.main()
