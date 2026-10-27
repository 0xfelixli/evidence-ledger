"""Bounded GETs to two fixed public registries; retain every received body."""

import json
import os
import socket
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPException, IncompleteRead
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .model import SourceError, sha256

MAX_BODY = 16 * 1024 * 1024
ALLOWED_HOSTS = {"registry.npmjs.org", "pypi.org"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in ALLOWED_HOSTS
        or parts.port not in (None, 443)
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise SourceError("source URL must be HTTPS on an approved public registry")
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Unexpected redirects are evidence of a changed source, never a successful fetch.
        return None


@dataclass
class Response:
    url: str
    status: Optional[int]
    headers: Dict[str, str]
    body: bytes
    fetched_at: str
    elapsed_ms: int
    error: Optional[str] = None
    truncated: bool = False

    def receipt(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "http_status": self.status,
            "headers": self.headers,
            "fetched_at": self.fetched_at,
            "elapsed_ms": self.elapsed_ms,
            "sha256": sha256(self.body),
            "bytes": len(self.body),
            "error": self.error,
            "truncated": self.truncated,
        }


class Transport:
    def __init__(self, timeout: float = 15.0, retries: int = 1):
        if not 0 < timeout <= 120 or not 0 <= retries <= 3:
            raise ValueError("timeout must be (0,120] and retries between 0 and 3")
        self.timeout = timeout
        self.retries = retries
        # No ambient credentials, proxies, cookies or tokens are sent by this tool.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def once(self, url: str) -> Response:
        validate_url(url)
        started = time.monotonic()
        at = utcnow()
        status = None
        headers = {}
        body = b""
        error = None
        truncated = False
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "EvidenceLedger/0.1 (read-only catalog audit)",
                "Accept-Encoding": "identity",
            },
        )
        try:
            try:
                result = self.opener.open(request, timeout=self.timeout)
            except HTTPError as exc:
                result = exc
            with result:
                status = result.code
                # Never persist Set-Cookie or unrelated response headers.
                headers = {
                    k.lower(): v
                    for k, v in result.headers.items()
                    if k.lower()
                    in {
                        "content-type",
                        "content-length",
                        "etag",
                        "last-modified",
                        "date",
                        "retry-after",
                        "x-pypi-last-serial",
                        "content-encoding",
                        "location",
                    }
                }
                body = result.read(MAX_BODY + 1)
                if len(body) > MAX_BODY:
                    body = body[:MAX_BODY]
                    error = "response exceeds 16 MiB"
                    truncated = True
        except (URLError, TimeoutError, socket.timeout, OSError, HTTPException) as exc:
            if isinstance(exc, IncompleteRead):
                body = exc.partial[:MAX_BODY]
                truncated = True
            error = type(exc).__name__ + ": " + str(exc)
        return Response(
            url,
            status,
            headers,
            body,
            at,
            round((time.monotonic() - started) * 1000),
            error,
            truncated,
        )

    def get(self, url: str) -> List[Response]:
        responses = []
        for attempt in range(self.retries + 1):
            response = self.once(url)
            responses.append(response)
            retry = response.error is not None or response.status in {429, 500, 502, 503, 504}
            if not retry or attempt == self.retries:
                break
            # Respect a short Retry-After. If the server wants a long wait, stop
            # rather than ignoring it or blocking a whole audit indefinitely.
            retry_after = response.headers.get("retry-after", "")
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    break
                if not 0 <= delay <= 3:
                    break
            else:
                delay = 0.25 * (2**attempt)
            time.sleep(delay)
        return responses


def parse_response(response: Response) -> Dict[str, Any]:
    if response.error or response.truncated:
        raise SourceError(response.error or "truncated response")
    if response.status != 200:
        raise SourceError("registry HTTP status %s" % response.status)
    mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if mime != "application/json" and not (
        mime.startswith("application/") and mime.endswith("+json")
    ):
        raise SourceError("expected JSON Content-Type, received " + (mime or "none"))
    try:

        def reject_constant(value):
            raise ValueError("non-finite JSON number " + value)

        def unique_object(pairs):
            obj = {}
            for k, v in pairs:
                if k in obj:
                    raise ValueError("duplicate JSON key: " + k)
                obj[k] = v
            return obj

        data = json.loads(
            response.body.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
        pending = [data]
        while pending:
            value = pending.pop()
            if isinstance(value, str):
                value.encode("utf-8")  # Reject unpaired surrogate escapes.
            elif isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise SourceError("invalid registry JSON: " + str(exc)) from exc
    if not isinstance(data, dict):
        raise SourceError("registry JSON must be an object")
    return data


def archive_response(response: Response, root: Path) -> Dict[str, Any]:
    receipt = response.receipt()
    relative = "evidence/" + receipt["sha256"] + ".json"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    # Content-addressed objects can safely be shared by duplicate observations.
    if not target.exists():
        # Different failed requests can have identical bodies. Publish each
        # content-addressed object atomically so concurrent readers never see
        # a half-written object from another worker.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=str(target.parent), delete=False) as file:
                temporary = Path(file.name)
                file.write(response.body)
            os.replace(temporary, target)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
    elif sha256(target.read_bytes()) != receipt["sha256"]:
        raise SourceError("existing evidence object failed integrity check")
    receipt["body_path"] = relative
    return receipt


def registry_url(ecosystem: str, package: str, selector: str) -> str:
    if ecosystem == "npm":
        return validate_url(
            "https://registry.npmjs.org/"
            + quote(package, safe="@")
            + "/"
            + quote(selector, safe="")
        )
    if ecosystem == "pypi":
        suffix = "/json" if selector == "latest" else "/" + quote(selector, safe="") + "/json"
        return validate_url("https://pypi.org/pypi/" + quote(package, safe="") + suffix)
    raise SourceError("unsupported registry")
