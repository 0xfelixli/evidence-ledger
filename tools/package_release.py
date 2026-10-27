"""Build a portable handover from an inspected sdist and verified evidence.

Only explicitly supplied distributions and evidence directories are read. No
credentials, working-tree globs, network access or background jobs are needed.
"""

import argparse
import html
import json
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evidence_ledger.audit import safe_file, verify_bundle  # noqa: E402
from evidence_ledger.history import verify_history  # noqa: E402
from evidence_ledger.model import InputError, sha256  # noqa: E402
from evidence_ledger.transport import utcnow  # noqa: E402


def write_bytes(archive, relative, raw, mode=0o644):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise InputError("unsafe release path")
    target = "evidence-ledger/" + path.as_posix()
    try:
        archive.getinfo(target)
    except KeyError:
        pass
    else:
        raise InputError("duplicate release path: " + relative)
    info = zipfile.ZipInfo(target)
    info.external_attr = (0o100000 | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, raw)


def add_tree(archive, root, prefix):
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise InputError("release evidence must contain regular files only")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            write_bytes(archive, prefix + "/" + relative, safe_file(root, relative).read_bytes())


def build(sdist, wheel, history, cloud, output):
    if output.exists():
        raise InputError("release output already exists")
    history_result = verify_history(history)
    if history_result["status"] == "running" or not history_result["sealed"]:
        raise InputError("release history must have ended and been sealed")
    cloud_result = verify_bundle(cloud) if cloud else None
    receipt = {
        "format_version": 1,
        "built_at": utcnow(),
        "sdist_sha256": sha256(sdist.read_bytes()),
        "wheel_sha256": sha256(wheel.read_bytes()),
        "history": {k: v for k, v in history_result.items() if k != "files_to_seal"},
        "cloud_summary": cloud_result["report"]["summary"] if cloud_result else None,
        "scope": "Saved evidence, internally verified. No signature, trusted timestamp, customer acceptance or earnings claim.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".release-", dir=str(output.parent)) as temporary:
        stage = Path(temporary)
        portable = stage / "evidence-ledger-portable.zip"
        with zipfile.ZipFile(portable, "w") as archive:
            with tarfile.open(sdist, "r:gz") as source:
                members = source.getmembers()
                if len(members) > 5000 or sum(m.size for m in members) > 64 * 1024 * 1024:
                    raise InputError("source distribution exceeds release builder limits")
                if any(not PurePosixPath(m.name).parts for m in members):
                    raise InputError("empty source distribution path")
                roots = {PurePosixPath(m.name).parts[0] for m in members}
                if len(roots) != 1:
                    raise InputError("source distribution must have one root directory")
                seen = set()
                for member in members:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or ".." in path.parts or "\\" in member.name:
                        raise InputError("unsafe source distribution path")
                    if member.isdir():
                        continue
                    if not member.isfile() or len(path.parts) < 2:
                        raise InputError("source distribution must contain regular files only")
                    relative = PurePosixPath(*path.parts[1:]).as_posix()
                    if relative in seen or relative.startswith("artifacts/maintenance-pilot/"):
                        raise InputError("duplicate/reserved source distribution path")
                    seen.add(relative)
                    write_bytes(
                        archive, relative, source.extractfile(member).read(), member.mode & 0o777
                    )
            add_tree(archive, history, "artifacts/maintenance-pilot")
            if cloud:
                add_tree(archive, cloud, "artifacts/cloud-run")
            write_bytes(
                archive, "release-index.json", (json.dumps(receipt, indent=2) + "\n").encode()
            )
            title = "Evidence Ledger · 可复核交付包"
            body = (
                """<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>%s</title>
<style>body{font:16px/1.8 -apple-system,sans-serif;background:#f5f5ee;color:#173b3a;margin:0}main{max-width:820px;margin:auto;padding:45px 24px}a{color:#245d47}li{margin:15px 0}pre{padding:20px;background:#e7ede2;overflow:auto}small{color:#63756e}</style>
<main>
<small>EVIDENCE LEDGER / VERIFIED HANDOVER</small>
<h1>%s</h1>
<p>持续巡检已封存：%s 轮完成，%s 轮失败；每轮 %s 条输入记录，对应 %s 个不同的软件包查询；合计 %s 次记录观察，其中 %s 次无法核实。重复观察不计作新的独立发现。</p>
<ul>
<li>
<a href="index.html">工具介绍与真实目录案例</a>
</li>
<li>
<a href="artifacts/maintenance-pilot/index.html">持续巡检：逐轮报告与来源证据</a>
</li>%s<li>
<a href="README.md">中文使用说明</a> · <a href="README.en.md">English documentation</a>
</li>
<li>
<a href="release-index.json">交付数据与分发包哈希</a>
</li>
</ul>
<p>解压后，在此目录运行以下命令即可离线复核：</p>
<pre>python3 run.py verify artifacts/catalog-reviewed\npython3 run.py verify-history artifacts/maintenance-pilot</pre>
<p>
<small>差异需要人工审核。哈希与离线重算证明内部一致性，不提供独立签名、可信采集时间或收入承诺。持续巡检运行状态：%s。</small>
</p>
</main>
</html>"""
                % (
                    html.escape(title),
                    html.escape(title),
                    history_result["completed_rounds_verified"],
                    history_result["failed_rounds"],
                    history_result["unique_input_records"],
                    history_result["unique_package_queries_per_round"],
                    history_result["record_observations_verified"],
                    history_result["unavailable_record_observations"],
                    '<li><a href="artifacts/cloud-run/report.html">独立保存的云端巡检报告</a></li>'
                    if cloud
                    else "",
                    html.escape(history_result["status"]),
                )
            )
            write_bytes(archive, "DELIVERY.html", body.encode())
        # Verify the actual portable bytes, not only the directories copied in.
        with tempfile.TemporaryDirectory() as unpacked:
            with zipfile.ZipFile(portable) as archive:
                archive.extractall(unpacked)
            root = Path(unpacked) / "evidence-ledger"
            verify_bundle(root / "artifacts/catalog-reviewed")
            verify_history(root / "artifacts/maintenance-pilot")
            if cloud:
                verify_bundle(root / "artifacts/cloud-run")
        shutil.copyfile(sdist, stage / sdist.name)
        shutil.copyfile(wheel, stage / wheel.name)
        (stage / "release-index.json").write_text(json.dumps(receipt, indent=2) + "\n")
        sums = [sha256(p.read_bytes()) + "  " + p.name for p in sorted(stage.iterdir())]
        (stage / "SHA256SUMS").write_text("\n".join(sums) + "\n")
        output.mkdir()  # Reserve without reusing an existing destination.
        try:
            stage.rename(output)
        except BaseException:
            output.rmdir()
            raise
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdist", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--history", required=True, type=Path)
    parser.add_argument("--cloud", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.sdist, args.wheel, args.history, args.cloud, args.out)))
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        parser.exit(3, "Release error: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
