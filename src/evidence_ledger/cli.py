"""Command-line entry point. Nonzero status distinguishes unknown from findings."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .audit import run_audit, verify_bundle
from .model import InputError, SourceError
from .transport import Transport


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="evidence-ledger",
        description="Read-only npm/PyPI catalog audit with saved evidence. Python 3.9+, no third-party dependencies.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser(
        "audit", help="query official registries and write a new self-contained report"
    )
    audit.add_argument("input", type=Path, help="UTF-8 CSV; record_id,ecosystem,package required")
    audit.add_argument(
        "--out", type=Path, required=True, help="new output directory (never overwritten)"
    )
    audit.add_argument(
        "--workers", type=int, default=4, help="1–8 concurrent source requests (default 4)"
    )
    audit.add_argument(
        "--timeout",
        type=float,
        default=15,
        help="per-request socket timeout in seconds (default 15)",
    )
    audit.add_argument(
        "--retries",
        type=int,
        default=1,
        help="0–3 bounded retries for transient failures (default 1)",
    )
    audit.add_argument(
        "--fail-on-change",
        action="store_true",
        help="exit 1 if any differences; unavailable always exits 2",
    )
    verify = sub.add_parser(
        "verify",
        help="offline integrity and deterministic result recomputation; never queries network",
    )
    verify.add_argument("bundle", type=Path)
    history_check = sub.add_parser(
        "verify-history", help="offline verification of completed rounds and history deltas"
    )
    history_check.add_argument("history", type=Path)
    history_seal = sub.add_parser(
        "seal-history", help="seal an ended history after offline verification"
    )
    history_seal.add_argument("history", type=Path)
    diff = sub.add_parser(
        "diff", help="compare two verified bundles offline; unavailable is never unchanged"
    )
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    monitor = sub.add_parser(
        "watch", help="bounded foreground maintenance run; no daemon or system schedule installed"
    )
    monitor.add_argument("input", type=Path)
    monitor.add_argument("--out", type=Path, required=True)
    monitor.add_argument(
        "--duration",
        type=float,
        required=True,
        help="stop starting new scans after 1–86400 seconds",
    )
    monitor.add_argument(
        "--interval", type=float, default=900, help="60–86400 seconds; first sample is immediate"
    )
    monitor.add_argument("--workers", type=int, default=4)
    monitor.add_argument("--timeout", type=float, default=15)
    monitor.add_argument("--retries", type=int, default=1)
    workbench = sub.add_parser(
        "serve", help="local browser workbench (127.0.0.1 only); no system service installed"
    )
    workbench.add_argument("--out", type=Path, default=Path("runs/workbench"))
    workbench.add_argument("--port", type=int, default=0, help="0 chooses a free loopback port")
    workbench.add_argument("--open", action="store_true", help="open your default browser")
    workbench.add_argument("--example", type=Path, help="optional CSV for the load-example button")
    args = parser.parse_args(argv)
    try:
        if args.command in {"verify-history", "seal-history"}:
            from .history import seal_history, verify_history

            operation = verify_history if args.command == "verify-history" else seal_history
            result = operation(args.history)
            print(
                json.dumps(
                    {k: v for k, v in result.items() if k != "files_to_seal"}, ensure_ascii=False
                )
            )
            return 0
        if args.command == "serve":
            from .workbench import serve

            if not 0 <= args.port <= 65535:
                raise InputError("port must be 0–65535")
            serve(args.out, args.port, args.open, args.example)
            return 0
        if args.command == "diff":
            from .history import compare_bundles

            print(
                json.dumps(compare_bundles(args.before, args.after), ensure_ascii=False, indent=2)
            )
            return 0
        if args.command == "watch":
            from .history import watch

            def progress(entry):
                print(json.dumps(entry, ensure_ascii=False), flush=True)

            result = watch(
                args.input,
                args.out,
                args.duration,
                args.interval,
                Transport(args.timeout, args.retries),
                args.workers,
                progress,
            )
            return (
                2
                if any(
                    e.get("error") or e.get("summary", {}).get("unavailable")
                    for e in result["runs"]
                )
                else 0
            )
        if args.command == "verify":
            result = verify_bundle(args.bundle)
            print(
                json.dumps({k: v for k, v in result.items() if k != "report"}, ensure_ascii=False)
            )
            return 0
        report = run_audit(
            args.input, args.out, Transport(args.timeout, args.retries), args.workers
        )
        print(
            json.dumps(
                {"report": str(args.out.resolve() / "report.html"), "summary": report["summary"]},
                ensure_ascii=False,
            )
        )
        if report["summary"]["unavailable"]:
            return 2
        if args.fail_on_change and report["summary"]["differences"]:
            return 1
        return 0
    except (InputError, SourceError, OSError, ValueError) as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("cancelled: no incomplete bundle was published", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
