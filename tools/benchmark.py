#!/usr/bin/env python3
"""Synthetic-volume benchmark using a saved official response, never live traffic.

IDs and repeated rows are synthetic. Its generated report is explicitly marked
benchmark in the title reference; it is not a second real-world case study.
"""

import argparse
import csv
import io
import json
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from evidence_ledger.audit import run_audit, verify_bundle  # noqa: E402
from evidence_ledger.transport import Response  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.rows <= 10000:
        parser.error("rows must be 1–10000")
    bundle = ROOT / "artifacts/catalog-reviewed"
    saved = json.loads((bundle / "report.json").read_text())
    seed = next(r for r in saved["results"] if r["record"]["package"] == "iso-filecoin-react")
    receipt = seed["receipts"][-1]
    body = (bundle / receipt["body_path"]).read_bytes()
    calls = []

    class OfflineSource:
        def get(self, url):
            calls.append(url)
            return [
                Response(
                    url,
                    receipt["http_status"],
                    receipt["headers"],
                    body,
                    receipt["fetched_at"],
                    receipt["elapsed_ms"],
                )
            ]

    text = io.StringIO(newline="")
    writer = csv.writer(text)
    writer.writerow(["record_id", "ecosystem", "package", "expected_dependencies", "source_ref"])
    for i in range(args.rows):
        writer.writerow(
            [
                "synthetic-%05d" % i,
                "npm",
                "iso-filecoin-react",
                json.dumps(seed["record"]["expected"]["dependencies"]),
                "SYNTHETIC VOLUME BENCHMARK: repeated rows; saved response replay, no live query",
            ]
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    input_path = args.out.parent / (args.out.name + "-input.csv")
    input_path.write_text(text.getvalue())
    started = time.perf_counter()
    tracemalloc.start()
    run_audit(input_path, args.out, transport=OfflineSource(), mode="offline")
    audit_seconds = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    started = time.perf_counter()
    verify_bundle(args.out)
    verify_seconds = time.perf_counter() - started
    measurements = {
        "synthetic_rows": args.rows,
        "network_requests": 0,
        "saved_source_reads": len(calls),
        "audit_seconds_with_tracemalloc": round(audit_seconds, 3),
        "verify_seconds": round(verify_seconds, 3),
        "python_peak_traced_bytes": peak,
        "html_bytes": (args.out / "report.html").stat().st_size,
        "scope": "Synthetic repeated-row throughput and HTML scaling; not unique package coverage or customer time saved.",
    }
    print(json.dumps(measurements, indent=2))
    (args.out.parent / (args.out.name + "-measurements.json")).write_text(
        json.dumps(measurements, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
