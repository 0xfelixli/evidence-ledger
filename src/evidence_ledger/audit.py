"""Audit orchestration and self-contained evidence bundles."""

import json
import shutil
import tempfile
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from . import __version__
from .model import MAX_INPUT_BYTES, InputError, Record, SourceError, parse_csv, sha256
from .registry import compare, normalize
from .transport import (
    Response,
    Transport,
    archive_response,
    parse_response,
    registry_url,
    utcnow,
    validate_url,
)

FORMAT_VERSION = 1
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_RESULT_BYTES = 64 * 1024 * 1024


def dump_json(path: Path, value: Any):
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def summary(results: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {k: 0 for k in ("changed", "unchanged", "observed", "unavailable")}
    for result in results:
        counts[result["state"]] += 1
    counts["total"] = len(results)
    counts["compared"] = sum(1 for r in results if r["record"]["expected"])
    counts["differences"] = sum(len(r["differences"]) for r in results)
    return counts


def finish_bundle(root: Path, report: Dict[str, Any]):
    from .render import render_reports

    report["summary"] = summary(report["results"])
    dump_json(root / "report.json", report)
    render_reports(root, report)
    # The manifest detects accidental corruption. It is not a digital signature.
    paths = [p for p in root.rglob("*") if p.is_file() and p.name != "manifest.json"]
    manifest = {
        "format_version": FORMAT_VERSION,
        "algorithm": "sha256",
        "files": {p.relative_to(root).as_posix(): sha256(p.read_bytes()) for p in sorted(paths)},
    }
    dump_json(root / "manifest.json", manifest)


def run_audit(
    input_path: Path,
    output: Path,
    transport: Optional[Transport] = None,
    workers: int = 4,
    mode: str = "live",
) -> Dict[str, Any]:
    if not 1 <= workers <= 8:
        raise InputError("workers must be between 1 and 8")
    if mode not in {"live", "offline"}:
        raise InputError("mode must be live or offline")
    with input_path.open("rb") as source:
        raw = source.read(MAX_INPUT_BYTES + 1)
    records = parse_csv(raw)
    output = output.resolve()
    if output.exists():
        raise InputError("output already exists; use a new directory to preserve prior evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".evidence-ledger-", dir=str(output.parent)))
    started = utcnow()
    reserved = False
    try:
        (stage / "input.csv").write_bytes(raw)
        client = transport or Transport()
        # Fetch each unique identity+selector once. Different comparison scopes reuse
        # the source response, then normalize separately. Stable output ordering.
        groups = {}
        for record in records:
            groups.setdefault((record.ecosystem, record.package, record.selector), []).append(
                record
            )
        budget_lock = threading.Lock()
        archive_hashes = set()
        archive_bytes = 0
        result_bytes = 0

        def fetch(group):
            nonlocal archive_bytes, result_bytes
            url = registry_url(*group)
            responses = client.get(url)
            if not responses:
                raise SourceError("transport returned no responses")
            receipts = []
            for response in responses:
                if response.url != url:
                    raise SourceError("transport source mismatch")
                digest = sha256(response.body)
                with budget_lock:
                    if digest not in archive_hashes:
                        if archive_bytes + len(response.body) > MAX_ARCHIVE_BYTES:
                            raise InputError(
                                "evidence exceeds 256 MiB per run; split the input into smaller batches"
                            )
                        archive_hashes.add(digest)
                        archive_bytes += len(response.body)
                receipts.append(archive_response(response, stage))
            normalized = {}
            output = []
            try:
                payload = parse_response(responses[-1])
                source_error = None
            except SourceError as exc:
                payload = None
                source_error = str(exc)
            for record in groups[group]:
                result = {
                    "record": record.as_dict(),
                    "source_url": url,
                    "receipts": receipts,
                    "observed": None,
                    "state": "unavailable",
                    "differences": [],
                    "unknown_fields": [],
                    "error": source_error,
                }
                if payload is not None:
                    try:
                        if record.dependency_scope not in normalized:
                            normalized[record.dependency_scope] = normalize(payload, record)
                        observed = normalized[record.dependency_scope]
                        result["observed"] = observed
                        result.update(compare(record, observed))
                    except SourceError as exc:
                        result["error"] = str(exc)
                size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
                with budget_lock:
                    if result_bytes + size > MAX_RESULT_BYTES:
                        raise InputError(
                            "normalized results exceed 64 MiB per run; split the input into smaller batches"
                        )
                    result_bytes += size
                output.append(result)
            return output

        keys = list(groups)
        completed = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            iterator = iter(keys)
            pending = {}
            for _ in range(min(workers, len(keys))):
                key = next(iterator)
                pending[executor.submit(fetch, key)] = key
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    key = pending.pop(future)
                    completed[key] = future.result()
                    next_key = next(iterator, None)
                    if next_key is not None:
                        pending[executor.submit(fetch, next_key)] = next_key
        by_id = {
            result["record"]["record_id"]: result
            for group in completed.values()
            for result in group
        }
        results = [by_id[record.record_id] for record in records]
        report = {
            "format_version": FORMAT_VERSION,
            "render_version": 2,
            "tool_version": __version__,
            "mode": mode,
            "started_at": started,
            "finished_at": utcnow(),
            "input_sha256": sha256(raw),
            "unique_sources": len(keys),
            "results": results,
            "scope": "Publisher-declared package metadata; differences require human review. Not vulnerability scanning, installability testing, or upgrade advice.",
        }
        finish_bundle(stage, report)
        # Destination is never reused. On a single filesystem rename publishes a complete bundle.
        try:
            output.mkdir()
        except FileExistsError as exc:
            raise InputError("output appeared during audit; refusing to overwrite") from exc
        reserved = True
        stage.rename(output)
        reserved = False
        return report
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        if reserved:
            try:
                output.rmdir()  # Only our still-empty reservation can be removed.
            except OSError:
                pass
        raise


def safe_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise InputError("unsafe bundle path")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or any(p in {"..", "."} for p in parts.parts):
        raise InputError("unsafe bundle path: " + relative)
    candidate = root / relative
    if candidate.is_symlink() or any(p.is_symlink() for p in candidate.parents if p != root.parent):
        raise InputError("symlinks are not allowed in bundles")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise InputError("bundle path escapes root")
    return candidate


def verify_bundle(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if (
            manifest.get("format_version") != FORMAT_VERSION
            or manifest.get("algorithm") != "sha256"
        ):
            raise InputError("unsupported manifest format")
        entries = manifest.get("files")
        if (
            not isinstance(entries, dict)
            or not entries
            or "input.csv" not in entries
            or "report.json" not in entries
        ):
            raise InputError("manifest is missing required files")
        required_files = {
            "input.csv",
            "report.json",
            "report.html",
            "review.csv",
            "corrections.csv",
        }
        if not required_files.issubset(entries):
            raise InputError("manifest is missing generated report files")
        for relative, expected in entries.items():
            path = safe_file(root, relative)
            if (
                not isinstance(expected, str)
                or len(expected) != 64
                or sha256(path.read_bytes()) != expected
            ):
                raise InputError("integrity failure: " + relative)
        actual_files = {
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and p.name != "manifest.json"
        }
        if actual_files != set(entries):
            raise InputError("bundle file list differs from manifest")
        report = json.loads(safe_file(root, "report.json").read_text(encoding="utf-8"))
        if report.get("format_version") != FORMAT_VERSION:
            raise InputError("unsupported report format")
        raw = safe_file(root, "input.csv").read_bytes()
        if sha256(raw) != report.get("input_sha256"):
            raise InputError("input hash does not match report")
        records = parse_csv(raw)
        results = report.get("results")
        if not isinstance(results, list) or len(results) != len(records):
            raise InputError("report record count does not match input")
        for record, result in zip(records, results):
            if result.get("record") != record.as_dict():
                raise InputError("report record identity/expectations differ from input")
            url = registry_url(record.ecosystem, record.package, record.selector)
            if result.get("source_url") != url:
                raise InputError("report source URL does not match record")
            receipts = result.get("receipts")
            if not isinstance(receipts, list) or not receipts:
                raise InputError("record has no source receipts")
            for receipt in receipts:
                if receipt.get("url") != url:
                    raise InputError("receipt URL does not match record")
                validate_url(receipt["url"])
                body_path = receipt.get("body_path")
                if body_path not in entries:
                    raise InputError("evidence object missing from manifest")
                body = safe_file(root, body_path).read_bytes()
                digest = sha256(body)
                if digest != receipt.get("sha256") or len(body) != receipt.get("bytes"):
                    raise InputError("receipt hash/size mismatch")
                if body_path != "evidence/" + digest + ".json":
                    raise InputError("evidence path is not content-addressed")
                try:
                    at = datetime.fromisoformat(receipt["fetched_at"].replace("Z", "+00:00"))
                    if at.tzinfo is None:
                        raise ValueError("timestamp has no timezone")
                except (KeyError, ValueError, TypeError) as exc:
                    raise InputError("invalid receipt timestamp") from exc
            replayed = replay_result(root, record, result)
            for field in ("observed", "state", "differences", "unknown_fields", "error"):
                if replayed[field] != result.get(field):
                    raise InputError("recomputed result differs: " + record.record_id + "/" + field)
        if report.get("summary") != summary(results):
            raise InputError("summary does not match records")
        # Rebuild the user-facing exports too: rehashing an edited HTML file
        # must not make a false report agree with an otherwise valid JSON audit.
        from .render import render_reports

        with tempfile.TemporaryDirectory() as rebuilt:
            render_reports(Path(rebuilt), report)
            for name in ("report.html", "review.csv", "corrections.csv"):
                if (Path(rebuilt) / name).read_bytes() != safe_file(root, name).read_bytes():
                    raise InputError("recomputed export differs: " + name)
        return {
            "ok": True,
            "files_verified": len(entries),
            "records_verified": len(records),
            "report": report,
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError("invalid evidence bundle: " + str(exc)) from exc


def replay_result(root: Path, record: Record, saved: Dict[str, Any]) -> Dict[str, Any]:
    receipt = saved["receipts"][-1]
    response = Response(
        receipt["url"],
        receipt["http_status"],
        receipt["headers"],
        safe_file(root, receipt["body_path"]).read_bytes(),
        receipt["fetched_at"],
        receipt["elapsed_ms"],
        receipt["error"],
        receipt["truncated"],
    )
    result = {
        "observed": None,
        "state": "unavailable",
        "differences": [],
        "unknown_fields": [],
        "error": None,
    }
    try:
        observed = normalize(parse_response(response), record)
        result["observed"] = observed
        result.update(compare(record, observed))
    except SourceError as exc:
        result["error"] = str(exc)
    return result
