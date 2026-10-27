"""Strict input contract and canonical identities."""

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit


class InputError(ValueError):
    pass


class SourceError(ValueError):
    """The source was unavailable or cannot substantiate this observation."""


def canonical_name(ecosystem: str, value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 214:
        raise InputError("package must be a nonempty string of at most 214 characters")
    if ecosystem == "npm":
        # Conservative public package grammar; reject slashes outside scoped names.
        if not re.fullmatch(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*", value):
            raise InputError("invalid npm name: " + repr(value))
        if value in {".", ".."}:
            raise InputError("invalid npm name")
        return value
    if ecosystem == "pypi":
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", value):
            raise InputError("invalid PyPI name: " + repr(value))
        return re.sub(r"[-_.]+", "-", value).lower()
    raise InputError("ecosystem must be npm or pypi")


def validate_selector(value: str) -> str:
    if value == "latest":
        return value
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]{0,127}", value):
        raise InputError("selector must be latest or a specific published version")
    return value


def normalize_repository(value: str) -> str:
    """Normalize transport/trailing .git only; retain subdirectory/fragment identity."""
    if value.startswith("git+"):
        value = value[4:]
    if value.startswith("git://github.com/"):
        value = "https://github.com/" + value[len("git://github.com/") :]
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value[len("git@github.com:") :]
    parts = urlsplit(value)
    if parts.scheme in {"https", "http"} and parts.hostname:
        path = parts.path.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), path, parts.query, parts.fragment)
        )
    return value.rstrip("/")


@dataclass(frozen=True)
class Record:
    record_id: str
    ecosystem: str
    package: str
    selector: str = "latest"
    expected: Optional[Dict[str, Any]] = None
    dependency_scope: str = "runtime+peer"
    source_ref: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "ecosystem": self.ecosystem,
            "package": self.package,
            "selector": self.selector,
            "expected": self.expected or {},
            "dependency_scope": self.dependency_scope,
            "source_ref": self.source_ref,
        }


COLUMNS = [
    "record_id",
    "ecosystem",
    "package",
    "selector",
    "expected_version",
    "expected_license",
    "expected_repository",
    "expected_dependencies",
    "dependency_scope",
    "source_ref",
]
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 10000


def parse_csv(raw: bytes) -> List[Record]:
    if len(raw) > MAX_INPUT_BYTES:
        raise InputError("input exceeds 8 MiB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError("input must be UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    headers = reader.fieldnames
    if not headers or len(headers) != len(set(headers)):
        raise InputError("CSV headers must be present and unique")
    required = {"record_id", "ecosystem", "package"}
    if not required.issubset(headers):
        raise InputError("missing headers: " + ", ".join(sorted(required - set(headers))))
    if set(headers) - set(COLUMNS):
        raise InputError("unknown headers: " + ", ".join(sorted(set(headers) - set(COLUMNS))))
    records = []
    ids = set()
    try:
        for line, row in enumerate(reader, 2):
            if len(records) >= MAX_RECORDS:
                raise InputError("input exceeds 10000 records")
            if None in row or any(v is None for v in row.values()):
                raise InputError("row %d has wrong column count" % line)
            if any("\x00" in v for v in row.values()):
                raise InputError("row %d contains a NUL" % line)
            ident = row["record_id"]
            if not ident or len(ident) > 200 or any(ord(c) < 32 for c in ident):
                raise InputError(
                    "row %d: record_id must be 1–200 characters without controls" % line
                )
            if ident in ids:
                raise InputError("duplicate record_id: " + ident)
            ids.add(ident)
            eco = row["ecosystem"]
            package = canonical_name(eco, row["package"])
            selector = validate_selector(row.get("selector") or "latest")
            scope = row.get("dependency_scope") or (
                "runtime+peer" if eco == "npm" else "requires-dist"
            )
            if scope not in (
                {"runtime", "runtime+peer", "runtime+peer+optional"}
                if eco == "npm"
                else {"requires-dist"}
            ):
                raise InputError("row %d: invalid dependency_scope for %s" % (line, eco))
            expected = {}
            for field in ("version", "license", "repository"):
                value = row.get("expected_" + field, "")
                if value:
                    expected[field] = (
                        normalize_repository(value) if field == "repository" else value
                    )
            deps = row.get("expected_dependencies", "")
            if deps:
                try:
                    parsed = json.loads(deps)
                except (ValueError, TypeError) as exc:
                    raise InputError(
                        "row %d: expected_dependencies must be a JSON string array" % line
                    ) from exc
                if not isinstance(parsed, list) or any(
                    not isinstance(x, str) or not x for x in parsed
                ):
                    raise InputError(
                        "row %d: expected_dependencies must be a JSON string array" % line
                    )
                try:
                    for item in parsed:
                        item.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise InputError(
                        "row %d: dependency contains an unpaired Unicode surrogate" % line
                    ) from exc
                if len(parsed) != len(set(parsed)):
                    raise InputError("row %d: duplicate expected dependency" % line)
                expected["dependencies"] = sorted(parsed)
            records.append(
                Record(ident, eco, package, selector, expected, scope, row.get("source_ref", ""))
            )
    except csv.Error as exc:
        raise InputError("invalid CSV: " + str(exc)) from exc
    if not records:
        raise InputError("CSV contains no records")
    return records


def read_csv(path: Path) -> List[Record]:
    with path.open("rb") as source:
        return parse_csv(source.read(MAX_INPUT_BYTES + 1))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
