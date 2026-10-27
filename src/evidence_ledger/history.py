"""Compare verified snapshots without turning source failures into 'no changes'."""

import html
import os
import time
from pathlib import Path
from typing import Any, Dict

from .audit import dump_json, read_object, run_audit, verify_bundle
from .model import InputError, sha256
from .transport import Transport, utcnow

FIELDS = ("version", "license", "repository", "repository_directory", "dependencies", "deprecated")


def compare_reports(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    old = {r["record"]["record_id"]: r for r in before["results"]}
    new = {r["record"]["record_id"]: r for r in after["results"]}
    entries = []
    for ident in sorted(set(old) | set(new)):
        previous, current = old.get(ident), new.get(ident)
        delta = {"record_id": ident, "state": None, "changes": []}
        if previous is None:
            delta["state"] = "record_added"
        elif current is None:
            delta["state"] = "record_removed"
        elif previous["record"] != current["record"]:
            delta["state"] = "configuration_changed"
        elif current["state"] == "unavailable":
            delta["state"] = "unavailable"
            delta["error"] = current["error"]
        elif previous["state"] == "unavailable":
            delta["state"] = "recovered"
        else:
            old_obs, new_obs = previous["observed"], current["observed"]
            for field in FIELDS:
                before_value, after_value = old_obs.get(field), new_obs.get(field)
                if before_value != after_value:
                    delta["changes"].append(
                        {"field": field, "before": before_value, "after": after_value}
                    )
            delta["state"] = "source_changed" if delta["changes"] else "unchanged_verified"
        entries.append(delta)
    counts = {}
    for entry in entries:
        counts[entry["state"]] = counts.get(entry["state"], 0) + 1
    return {
        "format_version": 1,
        "before_finished_at": before["finished_at"],
        "after_finished_at": after["finished_at"],
        "summary": counts,
        "results": entries,
        "scope": "Comparison of saved verified observations. Missing source evidence is not an unchanged result; changed configuration is not a source change.",
    }


def compare_bundles(before: Path, after: Path) -> Dict[str, Any]:
    return compare_reports(verify_bundle(before)["report"], verify_bundle(after)["report"])


def atomic_json(path: Path, value: Any):
    temp = path.with_suffix(path.suffix + ".tmp")
    dump_json(temp, value)
    os.replace(temp, path)


def render_history(root: Path, index: Dict[str, Any]):
    states = {"running": "巡检进行中", "finished": "巡检已结束", "interrupted": "巡检已中止"}
    rows = []
    for entry in index["runs"]:
        if entry.get("error"):
            rows.append(
                "<tr><td>%s</td><td colspan='4'>本轮失败：%s</td></tr>"
                % (html.escape(entry["at"]), html.escape(entry["error"]))
            )
            continue
        counts = entry["summary"]
        delta = entry.get("delta_summary", {})
        delta_text = ", ".join("%s: %s" % (k, v) for k, v in sorted(delta.items())) or "首轮基线"
        # run ids are internally generated, never paths from a data source.
        rows.append(
            "<tr><td><a href='%s/report.html'>%s</a></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (
                entry["run"],
                html.escape(entry["at"]),
                counts["total"],
                counts["differences"],
                counts["unavailable"],
                html.escape(delta_text),
            )
        )
    body = (
        """<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='Content-Security-Policy' content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>Evidence Ledger · 持续巡检</title><style>body{font:15px/1.7 -apple-system,BlinkMacSystemFont,sans-serif;margin:0;background:#f6f7f2;color:#172f31}main{max-width:1100px;margin:auto;padding:40px 22px}h1{font-size:34px}a{color:#166653}table{border-collapse:collapse;width:100%%;background:white}td,th{padding:13px;text-align:left;border-bottom:1px solid #dce3db}th{font-size:12px;color:#607577}.table{overflow:auto}p{max-width:900px}.muted{color:#607577;font-size:13px}</style><main><p class='muted'>EVIDENCE LEDGER / CONTINUOUS CHECK</p><h1>%s</h1><p>开始：%s · 最后更新：%s</p><p>每轮均保留独立证据。目录断言差异与两轮间的来源变化分别统计；来源不可用不会被计为“没有变化”。本页面不自动刷新，查看新一轮结果请手动刷新。</p><div class='table'><table><thead><tr><th>采集时间 / 报告</th><th>记录数</th><th>目录字段差异</th><th>无法核实</th><th>与前一成功轮比较</th></tr></thead><tbody>%s</tbody></table></div><p class='muted'>unchanged_verified = 两轮均可核实且所比较的规范化字段一致；source_changed = 来源字段变化；unavailable = 本轮无法核实；recovered = 从不可核实恢复，不推断缺失期间发生了什么；configuration_changed = 输入配置发生变化。无收入、接单或自动修正承诺。运行中断或结束后不会继续后台执行。</p><p><a href='history.json'>完整运行记录 JSON</a></p></main></html>"""
        % (
            states[index["status"]],
            html.escape(index["started_at"]),
            html.escape(index["updated_at"]),
            "".join(rows),
        )
    )
    temp = root / "index.html.tmp"
    temp.write_text(body, encoding="utf-8")
    os.replace(temp, root / "index.html")


def watch(
    input_path: Path,
    output: Path,
    duration: float,
    interval: float,
    transport=None,
    workers: int = 4,
    on_run=None,
) -> Dict[str, Any]:
    if not 1 <= duration <= 24 * 3600:
        raise InputError("duration must be 1–86400 seconds")
    if not 60 <= interval <= 24 * 3600:
        raise InputError("interval must be 60–86400 seconds")
    if not 1 <= workers <= 8:
        raise InputError("workers must be between 1 and 8")
    if output.exists():
        raise InputError("history output already exists")
    # Freeze configuration once; edits to the user's input while watching do not
    # silently turn into source changes or shift the paid maintenance scope.
    from .model import MAX_INPUT_BYTES, parse_csv

    with input_path.open("rb") as source:
        raw = source.read(MAX_INPUT_BYTES + 1)
    parse_csv(raw)
    output.mkdir(parents=True)
    (output / "watch-input.csv").write_bytes(raw)
    index = {
        "format_version": 1,
        "status": "running",
        "started_at": utcnow(),
        "updated_at": utcnow(),
        "duration_seconds": duration,
        "interval_seconds": interval,
        "input_sha256": sha256(raw),
        "runs": [],
    }
    started = time.monotonic()
    deadline = started + duration
    previous = None
    client = transport or Transport()
    count = 0

    def persist():
        index["updated_at"] = utcnow()
        atomic_json(output / "history.json", index)
        render_history(output, index)

    persist()
    try:
        # First sample is immediate; subsequent samples skip missed slots instead
        # of firing catch-up bursts. No sample starts at/after the stop deadline.
        next_at = started
        while time.monotonic() < deadline:
            if time.monotonic() < next_at:
                time.sleep(min(next_at - time.monotonic(), deadline - time.monotonic(), 1))
                continue
            count += 1
            run_id = "run-%03d" % count
            entry = {"at": utcnow(), "run": run_id}
            try:
                report = run_audit(output / "watch-input.csv", output / run_id, client, workers)
                verify_bundle(output / run_id)
                entry["summary"] = report["summary"]
                if previous is not None:
                    delta = compare_reports(previous, report)
                    dump_json(output / (run_id + "-delta.json"), delta)
                    entry["delta_summary"] = delta["summary"]
                previous = report
            except (OSError, ValueError) as exc:
                entry["error"] = str(exc)
            index["runs"].append(entry)
            persist()
            if on_run:
                on_run(entry)
            elapsed = time.monotonic() - started
            next_at = started + (int(elapsed // interval) + 1) * interval
        index["status"] = "finished"
    except KeyboardInterrupt:
        index["status"] = "interrupted"
        raise
    finally:
        persist()
    return index


def verify_history(root: Path) -> Dict[str, Any]:
    """Verify completed rounds, frozen input and deltas, including legacy live pilots."""
    import re
    import tempfile

    from .audit import safe_file
    from .model import parse_csv

    root = root.resolve()
    try:
        index = read_object(safe_file(root, "history.json"), 16 * 1024 * 1024)
        if index.get("format_version") != 1 or index.get("status") not in {
            "running",
            "finished",
            "interrupted",
        }:
            raise InputError("unsupported history format/status")
        if not all(isinstance(index.get(key), str) for key in ("started_at", "updated_at")):
            raise InputError("invalid history timestamps")
        raw = safe_file(root, "watch-input.csv").read_bytes()
        if sha256(raw) != index.get("input_sha256"):
            raise InputError("history input hash mismatch")
        records = parse_csv(raw)
        if not isinstance(index.get("runs"), list):
            raise InputError("history runs must be an array")
        files = {"history.json", "watch-input.csv", "index.html"}
        seen = set()
        previous = None
        verified = 0
        failed = 0
        unknown = 0
        for entry in index["runs"]:
            if not isinstance(entry, dict):
                raise InputError("history rounds must be objects")
            if not isinstance(entry.get("at"), str) or (
                entry.get("error") is not None and not isinstance(entry["error"], str)
            ):
                raise InputError("invalid history round metadata")
            name = entry.get("run")
            if (
                not isinstance(name, str)
                or not re.fullmatch(r"run-[0-9]{3,6}", name)
                or name in seen
            ):
                raise InputError("invalid/duplicate history run id")
            seen.add(name)
            if entry.get("error"):
                failed += 1
                continue
            run = safe_file(root, name)
            report = verify_bundle(run)["report"]
            if report["input_sha256"] != index["input_sha256"] or report["summary"] != entry.get(
                "summary"
            ):
                raise InputError("history round input/summary mismatch: " + name)
            files.add(name + "/manifest.json")
            if previous is not None:
                delta_name = name + "-delta.json"
                expected = compare_reports(previous, report)
                actual = read_object(safe_file(root, delta_name))
                if actual != expected or entry.get("delta_summary") != expected["summary"]:
                    raise InputError("history delta mismatch: " + name)
                files.add(delta_name)
            elif entry.get("delta_summary"):
                raise InputError("first completed round cannot have a delta")
            previous = report
            verified += 1
            unknown += report["summary"]["unavailable"]
        if index["status"] != "running":
            with tempfile.TemporaryDirectory() as temp:
                render_history(Path(temp), index)
                if (Path(temp) / "index.html").read_bytes() != safe_file(
                    root, "index.html"
                ).read_bytes():
                    raise InputError("history HTML does not match its records")
        seal_path = root / "history-manifest.json"
        sealed = seal_path.exists()
        if sealed:
            seal = read_object(safe_file(root, "history-manifest.json"), 16 * 1024 * 1024)
            if (
                index["status"] == "running"
                or seal.get("format_version") != 1
                or seal.get("algorithm") != "sha256"
                or not isinstance(seal.get("files"), dict)
                or set(seal.get("files", {})) != files
            ):
                raise InputError("invalid history seal")
            for name, digest in seal["files"].items():
                if sha256(safe_file(root, name).read_bytes()) != digest:
                    raise InputError("history seal hash mismatch: " + name)
        return {
            "ok": True,
            "status": index["status"],
            "sealed": sealed,
            "completed_rounds_verified": verified,
            "failed_rounds": failed,
            "unique_input_records": len(records),
            "unique_package_queries_per_round": len(
                {(r.ecosystem, r.package, r.selector) for r in records}
            ),
            "record_observations_verified": verified * len(records),
            "unavailable_record_observations": unknown,
            "files_to_seal": sorted(files),
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError("invalid maintenance history: " + str(exc)) from exc


def seal_history(root: Path) -> Dict[str, Any]:
    """Freeze an ended history's index and links to individually verified bundles."""
    from .audit import safe_file

    result = verify_history(root)
    if result["status"] == "running":
        raise InputError("cannot seal a running history")
    if result["sealed"]:
        raise InputError("history is already sealed")
    seal = {
        "format_version": 1,
        "algorithm": "sha256",
        "files": {
            name: sha256(safe_file(root.resolve(), name).read_bytes())
            for name in result["files_to_seal"]
        },
    }
    import json

    with (root / "history-manifest.json").open("x", encoding="utf-8") as file:
        file.write(json.dumps(seal, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return verify_history(root)
