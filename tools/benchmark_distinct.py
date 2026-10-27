"""Offline synthetic stress check: distinct fixtures, not real package research."""

import argparse
import csv
import json
import socket
import sys
import threading
import time
import tracemalloc
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evidence_ledger.audit import run_audit, verify_bundle  # noqa: E402
from evidence_ledger.model import InputError  # noqa: E402
from evidence_ledger.transport import Response  # noqa: E402


class SyntheticTransport:
    def __init__(self, faults):
        self.faults = faults
        self.lock = threading.Lock()
        self.calls = 0
        self.active = 0
        self.peak = 0

    def get(self, url):
        name = unquote(url.split("/")[-2])
        index = int(name.rsplit("-", 1)[1])
        with self.lock:
            self.calls += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.001)  # Permit overlap; this is simulated source latency.
            body = (
                {}
                if index < self.faults
                else {
                    "name": name,
                    "version": "2.0.0" if index < self.faults * 2 else "1.0.0",
                }
            )
            return [
                Response(
                    url,
                    200,
                    {"content-type": "application/json"},
                    json.dumps(body).encode(),
                    "2000-01-01T00:00:00Z",
                    1,
                )
            ]
        finally:
            with self.lock:
                self.active -= 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if not 200 <= args.records <= 5000 or not 1 <= args.workers <= 8:
        parser.error("records must be 200–5000 and workers 1–8")
    source = args.out.with_name(args.out.name + "-input.csv")
    if args.out.exists() or source.exists():
        parser.error("output/input already exists; choose a new name")
    source.parent.mkdir(parents=True, exist_ok=True)
    with source.open("x", encoding="utf-8", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(["record_id", "ecosystem", "package", "expected_version", "source_ref"])
        for index in range(args.records):
            name = "synthetic-evidence-ledger-%05d" % index
            writer.writerow(
                [name, "npm", name, "1.0.0", "Generated fixture; no real package fetched."]
            )
    faults = args.records // 50
    client = SyntheticTransport(faults)
    with (
        patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")),
        patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")),
    ):
        tracemalloc.start()
        started = time.perf_counter()
        report = run_audit(source, args.out, client, args.workers, mode="offline")
        audit_seconds = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        started = time.perf_counter()
        verification = verify_bundle(args.out)
        verify_seconds = time.perf_counter() - started
    expected = {
        "changed": faults,
        "unchanged": args.records - faults * 2,
        "observed": 0,
        "unavailable": faults,
        "total": args.records,
        "compared": args.records,
        "differences": faults,
    }
    if report["summary"] != expected or client.calls != args.records or client.peak > args.workers:
        raise InputError("synthetic benchmark invariant failed")
    metrics = {
        "benchmark_kind": "synthetic_distinct_sources",
        "real_network_requests": 0,
        "generated_records": args.records,
        "unique_fixture_queries": client.calls,
        "workers": args.workers,
        "maximum_concurrent_gets": client.peak,
        "summary": report["summary"],
        "offline_records_verified": verification["records_verified"],
        "audit_seconds_with_tracemalloc": round(audit_seconds, 3),
        "verify_seconds_without_tracemalloc": round(verify_seconds, 3),
        "peak_traced_python_allocation_during_audit_bytes": peak,
        "scope": "Artificial identities and responses with injected missing evidence and version differences. No real package research or live-registry throughput claim.",
    }
    path = args.out.with_name(args.out.name + "-metrics.json")
    with path.open("x", encoding="utf-8") as target:
        json.dump(metrics, target, indent=2)
        target.write("\n")
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
