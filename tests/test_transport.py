import io
import unittest
from http.client import IncompleteRead
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from evidence_ledger.model import SourceError
from evidence_ledger.transport import (
    MAX_BODY,
    NoRedirect,
    Response,
    Transport,
    parse_response,
    registry_url,
    validate_url,
)


class FakeHTTP:
    def __init__(self, body=b"{}", status=200, headers=None):
        self.body = body
        self.code = status
        self.headers = headers or {"Content-Type": "application/json"}
        self.requested = None

    def read(self, amount):
        self.requested = amount
        return self.body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TransportTests(unittest.TestCase):
    def response(self, body=b"{}", status=200, headers=None, **kwargs):
        return Response(
            "https://registry.npmjs.org/react/latest",
            status,
            headers or {"content-type": "application/json"},
            body,
            "2026-01-01T00:00:00Z",
            1,
            **kwargs,
        )

    def test_cannot_send_to_other_hosts_or_embed_credentials(self):
        for url in [
            "http://registry.npmjs.org/a",
            "https://registry.npmjs.org.evil.test/a",
            "https://evil.test/a",
            "https://user:secret@registry.npmjs.org/a",
            "https://registry.npmjs.org:8443/a",
            "https://127.0.0.1/a",
            "https://registry.npmjs.org/a?token=x",
            "https://pypi.org/a#frag",
        ]:
            with self.subTest(url=url), self.assertRaises(SourceError):
                validate_url(url)

    def test_scoped_url_is_encoded(self):
        self.assertEqual(
            registry_url("npm", "@a/b", "latest"), "https://registry.npmjs.org/@a%2Fb/latest"
        )
        self.assertEqual(
            registry_url("pypi", "requests", "2.32.0"), "https://pypi.org/pypi/requests/2.32.0/json"
        )

    def test_never_follows_redirect(self):
        self.assertIsNone(
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test")
        )

    def test_wrong_content_empty_invalid_and_error_not_success(self):
        responses = [
            self.response(b""),
            self.response(b"<html>oops</html>", headers={"content-type": "text/html"}),
            self.response(b"[]"),
            self.response(b'{"error":"oops"}', status=500),
            self.response(b'{"a":NaN}'),
            self.response(b'{"a":1,"a":2}'),
            self.response(b"\xff"),
            self.response(error="timeout"),
            self.response(truncated=True),
        ]
        for response in responses:
            with self.subTest(response=response), self.assertRaises(SourceError):
                parse_response(response)
        self.assertEqual(
            parse_response(
                self.response(
                    b'{"a":1}', headers={"content-type": "application/json; charset=utf-8"}
                )
            ),
            {"a": 1},
        )

    def test_response_size_bounded_and_marked_unknown(self):
        client = Transport(retries=0)
        fake = FakeHTTP(b"x" * (MAX_BODY + 2))
        with patch.object(client.opener, "open", return_value=fake):
            response = client.once("https://registry.npmjs.org/react/latest")
        self.assertEqual(fake.requested, MAX_BODY + 1)
        self.assertEqual(len(response.body), MAX_BODY)
        self.assertTrue(response.truncated)
        self.assertIsNotNone(response.error)

    def test_network_error_saved_as_receipt(self):
        client = Transport(retries=0)
        with patch.object(client.opener, "open", side_effect=URLError("offline")):
            response = client.once("https://pypi.org/pypi/requests/json")
        self.assertIsNone(response.status)
        self.assertIn("offline", response.error)
        self.assertEqual(response.body, b"")

    def test_mid_body_disconnect_is_unavailable_not_whole_run_crash(self):
        client = Transport(retries=0)
        fake = FakeHTTP()
        fake.read = lambda amount: (_ for _ in ()).throw(IncompleteRead(b'{"name":', 100))
        with patch.object(client.opener, "open", return_value=fake):
            response = client.once("https://registry.npmjs.org/react/latest")
        self.assertIn("IncompleteRead", response.error)
        with self.assertRaises(SourceError):
            parse_response(response)

    def test_http_error_body_is_retained(self):
        client = Transport(retries=0)
        error = HTTPError(
            "https://registry.npmjs.org/a/latest",
            404,
            "not found",
            {"Content-Type": "application/json"},
            io.BytesIO(b'{"error":"missing"}'),
        )
        with patch.object(client.opener, "open", side_effect=error):
            response = client.once("https://registry.npmjs.org/a/latest")
        self.assertEqual(response.status, 404)
        self.assertIn(b"missing", response.body)

    def test_retries_transient_only_and_respects_long_retry_after(self):
        client = Transport(retries=3)
        with (
            patch.object(
                client, "once", side_effect=[self.response(status=503), self.response()]
            ) as once,
            patch("evidence_ledger.transport.time.sleep"),
        ):
            self.assertEqual(len(client.get("https://registry.npmjs.org/a/latest")), 2)
            self.assertEqual(once.call_count, 2)
        for status, headers in [
            (404, {}),
            (429, {"retry-after": "60"}),
            (429, {"retry-after": "Wed, 01 Jan 2030 00:00:00 GMT"}),
        ]:
            with (
                patch.object(
                    client,
                    "once",
                    return_value=self.response(status=status, headers=headers or None),
                ) as once,
                patch("evidence_ledger.transport.time.sleep"),
            ):
                self.assertEqual(len(client.get("https://registry.npmjs.org/a/latest")), 1)
                self.assertEqual(once.call_count, 1)

    def test_no_tokens_cookies_or_proxy(self):
        client = Transport(retries=0)
        fake = FakeHTTP()
        with patch.object(client.opener, "open", return_value=fake) as call:
            client.once("https://pypi.org/pypi/requests/json")
        req = call.call_args.args[0]
        self.assertFalse(req.has_header("Authorization"))
        self.assertFalse(req.has_header("Cookie"))
        self.assertFalse(
            any(type(h).__name__ == "ProxyHandler" and h.proxies for h in client.opener.handlers)
        )


if __name__ == "__main__":
    unittest.main()
