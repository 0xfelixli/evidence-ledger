"""Loopback-only workbench for running the same auditor without shell commands."""

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .audit import run_audit
from .model import InputError, parse_csv
from .transport import Response, Transport, utcnow

MAX_WEB_INPUT = 2 * 1024 * 1024
MAX_WEB_RECORDS = 500


class JobManager:
    def __init__(self, root: Path, transport=None):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.jobs = {}
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.stop = threading.Event()
        client = transport or Transport(timeout=15, retries=1)
        stop = self.stop

        class StoppableTransport:
            def get(self, url):
                if stop.is_set():
                    return [Response(url, None, {}, b"", utcnow(), 0, "workbench stopped")]
                return client.get(url)

        self.transport = StoppableTransport()

    def submit(self, raw: bytes):
        if len(raw) > MAX_WEB_INPUT:
            raise InputError("网页输入最多 2 MiB；更大任务请分批或使用 CLI。")
        records = parse_csv(raw)
        if len(records) > MAX_WEB_RECORDS:
            raise InputError("网页每批最多 500 条记录；请分批或使用 CLI。")
        with self.lock:
            if self.stop.is_set():
                raise InputError("工作台正在结束，不能创建新任务。")
            active = sum(j["status"] in {"queued", "running"} for j in self.jobs.values())
            if active >= 3:
                raise InputError("已有三个排队或运行中的任务，请等完成后再试。")
            ident = uuid.uuid4().hex
            directory = self.root / ident
            directory.mkdir()
            (directory / "submitted.csv").write_bytes(raw)
            job = {
                "id": ident,
                "status": "queued",
                "created_at": utcnow(),
                "record_count": len(records),
                "summary": None,
                "error": None,
                "report_url": None,
            }
            self.jobs[ident] = job
            self.executor.submit(self._run, ident)
            return dict(job)

    def _run(self, ident):
        started = time.monotonic()
        with self.lock:
            self.jobs[ident]["status"] = "running"
        try:
            report = run_audit(
                self.root / ident / "submitted.csv", self.root / ident / "report", self.transport
            )
            with self.lock:
                self.jobs[ident].update(
                    status="completed",
                    summary=report["summary"],
                    report_url="/runs/" + ident + "/report.html",
                )
        except (OSError, ValueError) as exc:
            with self.lock:
                self.jobs[ident].update(status="failed", error=str(exc))
        finally:
            with self.lock:
                self.jobs[ident]["elapsed_seconds"] = round(time.monotonic() - started, 2)
                self.jobs[ident]["finished_at"] = utcnow()
                (self.root / ident / "job.json").write_text(
                    json.dumps(self.jobs[ident], ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

    def get(self, ident):
        with self.lock:
            value = self.jobs.get(ident)
            return dict(value) if value else None

    def all(self):
        with self.lock:
            return [dict(j) for j in reversed(list(self.jobs.values()))]

    def close(self):
        self.stop.set()
        self.executor.shutdown(wait=True)


def create_server(root: Path, port: int = 0, transport=None, example_path=None):
    manager = JobManager(root, transport)
    token = secrets.token_urlsafe(32)
    example = None
    if example_path:
        example = Path(example_path).read_bytes()
        parse_csv(example)

    class Handler(BaseHTTPRequestHandler):
        server_version = "EvidenceLedgerWorkbench/0.1"

        def log_message(self, format, *args):
            # Keep package names, CSRF tokens and input data out of access logs.
            return

        def allowed_host(self):
            return self.headers.get("Host") == "127.0.0.1:" + str(self.server.server_port)

        def origin(self):
            return "http://127.0.0.1:" + str(self.server.server_port)

        def send(self, code, body, mime="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def json(self, code, value):
            self.send(code, json.dumps(value, ensure_ascii=False, allow_nan=False).encode())

        def do_GET(self):
            if not self.allowed_host():
                return self.json(403, {"error": "invalid host"})
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return self.json(403, {"error": "cross-site access denied"})
            parts = urlsplit(self.path)
            if parts.query or parts.fragment:
                return self.json(400, {"error": "unexpected query"})
            path = parts.path
            if path == "/":
                return self.send(
                    200,
                    workbench_html(token, example is not None).encode(),
                    "text/html; charset=utf-8",
                )
            if path == "/api/jobs":
                return self.json(200, {"jobs": manager.all()})
            if path == "/api/example" and example is not None:
                return self.json(200, {"csv": example.decode("utf-8-sig")})
            match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})", path)
            if match:
                job = manager.get(match[1])
                return self.json(200 if job else 404, job or {"error": "job not found"})
            match = re.fullmatch(
                r"/runs/([a-f0-9]{32})/(report\.html|report\.json|review\.csv|corrections\.csv|input\.csv|manifest\.json|evidence/[a-f0-9]{64}\.json)",
                path,
            )
            if match:
                job = manager.get(match[1])
                if not job or job["status"] != "completed":
                    return self.json(404, {"error": "completed report not found"})
                file = manager.root / match[1] / "report" / match[2]
                if file.is_symlink() or not file.is_file():
                    return self.json(404, {"error": "file not found"})
                suffix = file.suffix
                mime = {
                    ".html": "text/html; charset=utf-8",
                    ".csv": "text/csv; charset=utf-8",
                    ".json": "application/json; charset=utf-8",
                }[suffix]
                return self.send(200, file.read_bytes(), mime)
            return self.json(404, {"error": "not found"})

        def do_POST(self):
            if (
                not self.allowed_host()
                or self.headers.get("Origin") != self.origin()
                or self.headers.get("Sec-Fetch-Site") == "cross-site"
            ):
                return self.json(403, {"error": "origin/host validation failed"})
            supplied = self.headers.get("X-Ledger-CSRF", "")
            if not supplied.isascii() or not hmac.compare_digest(supplied, token):
                return self.json(403, {"error": "invalid session token"})
            if self.path != "/api/jobs":
                return self.json(404, {"error": "not found"})
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                return self.json(415, {"error": "expected application/json"})
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self.json(411, {"error": "Content-Length required"})
            if not 0 < length <= MAX_WEB_INPUT * 6 + 4096:
                return self.json(413, {"error": "input too large or empty"})
            self.connection.settimeout(10)
            try:
                payload = self.rfile.read(length)
                if len(payload) != length:
                    raise InputError("incomplete request body")
                data = json.loads(payload.decode("utf-8"))
                if (
                    not isinstance(data, dict)
                    or set(data) != {"csv"}
                    or not isinstance(data["csv"], str)
                ):
                    raise InputError("expected one csv string")
                raw = data["csv"].encode("utf-8")
                job = manager.submit(raw)
            except (OSError, ValueError) as exc:
                return self.json(400, {"error": str(exc)})
            return self.json(202, job)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.manager = manager
    return server


def serve(root: Path, port=0, open_browser=False, example_path=None):
    server = create_server(root, port=port, example_path=example_path)
    url = "http://127.0.0.1:" + str(server.server_port)
    print("Evidence Ledger workbench: " + url, flush=True)
    print("Local only. Ctrl-C stops the workbench; saved reports remain on disk.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        server.manager.close()


def workbench_html(token, has_example):
    script_hash = base64.b64encode(hashlib.sha256(WORKBENCH_SCRIPT.encode()).digest()).decode()
    return (
        WORKBENCH_HTML.replace("__TOKEN__", token)
        .replace("__HASH__", script_hash)
        .replace("__EXAMPLE_DISABLED__", "" if has_example else "disabled")
        .replace("__SCRIPT__", WORKBENCH_SCRIPT)
    )


WORKBENCH_HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="csrf-token" content="__TOKEN__"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'sha256-__HASH__'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'"><title>Evidence Ledger · 本地巡检工作台</title><style>
:root{color-scheme:light}*{box-sizing:border-box}body{font:15px/1.65 -apple-system,BlinkMacSystemFont,sans-serif;background:#f6f7f2;color:#172f31;margin:0}main{max-width:1150px;padding:36px 24px 60px;margin:auto}.eyebrow{font-size:11px;font-weight:700;color:#166653;letter-spacing:2px}h1{font-size:38px;line-height:1.2;margin:12px 0}h2{font-size:19px;margin:0 0 8px}.muted{color:#607577}header{border-bottom:1px solid #dce3db;padding-bottom:24px}.grid{display:grid;grid-template-columns:1.15fr 1fr;gap:24px;margin-top:26px}.panel{background:white;border:1px solid #dce3db;border-radius:12px;padding:24px}button,input,select,textarea{font:inherit}button{background:#166653;border:1px solid #166653;color:white;border-radius:7px;padding:10px 15px;cursor:pointer}button.secondary{background:white;color:#166653}button:disabled{opacity:.45;cursor:default}textarea{width:100%;min-height:245px;resize:vertical;background:#fafbf8;border:1px solid #cbd8ce;border-radius:7px;padding:12px;font:12px/1.7 ui-monospace,monospace;margin:8px 0 16px}input[type=file]{max-width:100%;margin:10px 0}label{font-size:13px;display:block;font-weight:600}.buttons{display:flex;gap:10px;flex-wrap:wrap}.callout{padding:12px 15px;border-left:3px solid #166653;background:#eaf0e6;margin-top:18px;font-size:13px}.job{border:1px solid #dce3db;border-radius:8px;padding:15px;margin:12px 0;overflow-wrap:anywhere}.job strong{display:block}.job p{margin:6px 0}.status{font-size:12px;background:#e7eee4;border-radius:4px;padding:3px 8px;display:inline-block}.error{color:#9a3441;background:#f8e9ec;padding:12px;border-radius:6px;white-space:pre-wrap}.hidden{display:none}a{color:#166653;text-underline-offset:3px}.small{font-size:12px}footer{font-size:12px;color:#607577;margin-top:28px}button:focus-visible,input:focus-visible,textarea:focus-visible,a:focus-visible{outline:3px solid #79a88a;outline-offset:3px}@media(max-width:760px){main{padding:24px 16px}h1{font-size:30px}.grid{grid-template-columns:1fr}.panel{padding:18px}}
</style></head><body><main><header><div class="eyebrow">EVIDENCE LEDGER / LOCAL WORKBENCH</div><h1>把目录核对，变成可交付的证据。</h1><p class="muted">选择 CSV，运行只读巡检，得到带来源和差异的审核报告。</p></header><div class="grid"><section class="panel"><h2>创建一次巡检</h2><p class="muted small">必填列：record_id、ecosystem、package。填写 expected_* 才会比较；留空仅采集，不能算通过。</p><label for="file">从本地选择 CSV（最多 2 MiB / 500 条）</label><input id="file" type="file" accept=".csv,text/csv"><p id="filename" class="small muted"></p><label for="csv">或直接粘贴 CSV</label><textarea id="csv" spellcheck="false" aria-label="CSV 内容">record_id,ecosystem,package
npm-example,npm,iso-filecoin-react
python-example,pypi,requests
</textarea><div class="buttons"><button id="run" type="button">运行巡检</button><button id="example" class="secondary" type="button" __EXAMPLE_DISABLED__>载入真实目录案例</button></div><p id="error" class="error hidden" role="alert"></p><div class="callout">只查询官方 npm / PyPI，不安装或执行包，不自动修改目录。仅包名和版本选择器会发送到注册表；目录断言保留在本地。</div></section><section class="panel"><h2>本次工作台的任务</h2><p class="muted small">报告保存到本地。关闭本工作台后，可直接打开已保存的 report.html。页面每秒更新当前任务状态。</p><div id="jobs" aria-live="polite"></div></section></div><footer><p>发现差异 ≠ 安全漏洞或必须升级。可选 peer 与运行依赖需要区分；许可和仓库信息为发布者声明。每份报告保留采集时间、原始响应与 SHA-256，支持 CLI 离线复核。</p><p>本地服务只监听 127.0.0.1，不是公开网站，也不安装后台定时任务。退出终端中的工作台进程后停止接受新任务；已经发出的请求会结束后保存结果。</p></footer></main><script>__SCRIPT__</script></body></html>"""

WORKBENCH_SCRIPT = r""""use strict";
const $=id=>document.getElementById(id),token=document.querySelector('meta[name=csrf-token]').content;
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
function error(message){$('error').textContent=message||'';$('error').classList.toggle('hidden',!message);}
async function api(path,options={}){const r=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-Ledger-CSRF':token,...options.headers},signal:AbortSignal.timeout(15000)});const data=await r.json();if(!r.ok)throw new Error(data.error||('HTTP '+r.status));return data;}
$('file').addEventListener('change',async()=>{const file=$('file').files[0];if(!file)return;$('run').disabled=true;if(file.size>2097152){error('文件超过 2 MiB，未载入。请分批，或修改 CSV 内容后重试。');return;}try{$('csv').value=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());$('filename').textContent=file.name+' · '+file.size+' bytes';$('run').disabled=false;error('');}catch(e){error('文件必须是有效 UTF-8 CSV，未载入。'+e.message);}});
$('csv').addEventListener('input',()=>{$('run').disabled=false;});
$('example').addEventListener('click',async()=>{try{const data=await api('/api/example');$('csv').value=data.csv;$('filename').textContent='Chain.Love 固定提交的 24 条目录案例 · CC BY-SA 4.0';$('run').disabled=false;error('');}catch(e){error(e.message);}});
$('run').addEventListener('click',async()=>{$('run').disabled=true;error('');try{await api('/api/jobs',{method:'POST',body:JSON.stringify({csv:$('csv').value})});await refresh();}catch(e){error(e.message);}finally{$('run').disabled=false;}});
let last='';
async function refresh(){const data=await api('/api/jobs');const serialized=JSON.stringify(data.jobs);if(serialized===last)return;last=serialized;$('jobs').replaceChildren();if(!data.jobs.length){$('jobs').append(el('p','还没有任务。可以先用上方两条公开包名试运行。','muted'));return;}for(const job of data.jobs){const card=el('article',undefined,'job');const labels={queued:'排队中',running:'正在核对来源',completed:job.summary?.unavailable?'已完成 · 存在无法核实项':'已完成',failed:'运行失败'};card.append(el('span',labels[job.status],'status'),el('strong',job.record_count+' 条记录'),el('p',job.created_at,'small muted'));if(job.summary){const s=job.summary;card.append(el('p','差异 '+s.changed+' · 一致 '+s.unchanged+' · 仅采集 '+s.observed+' · 无法核实 '+s.unavailable));}if(job.error)card.append(el('p',job.error,'error'));if(job.report_url){const a=el('a','打开完整报告 →');a.href=job.report_url;a.target='_blank';a.rel='noopener';card.append(a);}if(job.elapsed_seconds!==undefined)card.append(el('p','耗时 '+job.elapsed_seconds+' 秒','small muted'));$('jobs').append(card);}}
async function poll(){try{await refresh();}catch(e){error('暂时无法连接本地工作台：'+e.message);}setTimeout(poll,1000);}poll();"""
