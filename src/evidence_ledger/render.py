"""Standalone HTML and spreadsheet-safe review exports. No network resources."""

import base64
import csv
import hashlib
import html
import json
from pathlib import Path
from typing import Any, Dict


def spreadsheet_safe(value: Any) -> str:
    text = str(value) if value is not None else ""
    # Guard spreadsheet formula injection, including whitespace/control prefixes.
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or text.startswith(
        ("\t", "\r", "\n")
    ):
        return "'" + text
    return text


def write_csv(path: Path, headers, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.writer(target)
        writer.writerow(headers)
        writer.writerows([[spreadsheet_safe(cell) for cell in row] for row in rows])


def render_reports(root: Path, report: Dict[str, Any]):
    rows = []
    corrections = []
    for result in report["results"]:
        rec = result["record"]
        observed = result["observed"] or {}
        receipt = result["receipts"][-1] if result["receipts"] else {}
        rows.append(
            [
                rec["record_id"],
                rec["ecosystem"],
                rec["package"],
                rec["selector"],
                result["state"],
                observed.get("version", ""),
                len(result["differences"]),
                ", ".join(result["unknown_fields"]),
                result["error"] or "",
                result["source_url"],
                receipt.get("fetched_at", ""),
                receipt.get("sha256", ""),
                rec["source_ref"],
            ]
        )
        for diff in result["differences"]:
            corrections.append(
                [
                    rec["record_id"],
                    rec["ecosystem"],
                    rec["package"],
                    observed.get("version", ""),
                    diff["field"],
                    json.dumps(diff["expected"], ensure_ascii=False),
                    json.dumps(diff["observed"], ensure_ascii=False),
                    result["state"],
                    "review_required",
                    result["source_url"],
                    receipt.get("fetched_at", ""),
                    receipt.get("sha256", ""),
                ]
            )
    write_csv(
        root / "review.csv",
        [
            "record_id",
            "ecosystem",
            "package",
            "selector",
            "state",
            "observed_version",
            "difference_count",
            "unknown_fields",
            "error",
            "source_url",
            "fetched_at",
            "evidence_sha256",
            "source_ref",
        ],
        rows,
    )
    write_csv(
        root / "corrections.csv",
        [
            "record_id",
            "ecosystem",
            "package",
            "observed_version",
            "field",
            "expected_json",
            "observed_json",
            "record_state",
            "decision",
            "source_url",
            "fetched_at",
            "evidence_sha256",
        ],
        corrections,
    )
    payload = json.dumps(
        report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    payload = (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    revision = report.get("render_version", 1)
    if revision not in (1, 2):
        raise ValueError("unsupported render revision")
    script = SCRIPT if revision == 1 else SCRIPT_V2
    template = TEMPLATE if revision == 1 else TEMPLATE_V2
    script_hash = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    csp = (
        "default-src 'none'; script-src 'sha256-%s'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; connect-src 'none'"
        % script_hash
    )
    document = (
        template.replace("__CSP__", html.escape(csp, quote=True))
        .replace("__PAYLOAD__", payload)
        .replace("__SCRIPT__", script)
    )
    (root / "report.html").write_text(document, encoding="utf-8")


TEMPLATE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="__CSP__"><title>Evidence Ledger · 数据质量巡检</title>
<style>
:root{color-scheme:light;--ink:#172f31;--muted:#607577;--paper:#f6f7f2;--line:#dce3db;--green:#166653;--orange:#9b4a12;--red:#9a3441;--blue:#315e8b}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:15px;line-height:1.65}main{max-width:1280px;margin:auto;padding:42px 36px 64px}a{color:var(--green);text-underline-offset:3px}button,input,select{font:inherit}button{cursor:pointer}header{border-bottom:1px solid var(--line);padding-bottom:24px;display:flex;gap:24px;align-items:flex-start;justify-content:space-between}.eyebrow{font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--green)}h1{font-size:clamp(26px,4vw,40px);line-height:1.2;margin:10px 0}h2{font-size:19px;margin:0 0 12px}p{margin:8px 0}.muted{color:var(--muted)}.edition{font-size:12px;color:var(--muted);text-align:right;min-width:180px}.mode{display:inline-block;background:#e7eee4;border:1px solid #ccdbcb;border-radius:999px;padding:4px 12px;font-size:12px;color:var(--green);font-weight:700}.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin:24px 0}.card{border:1px solid var(--line);border-radius:12px;padding:19px;background:#fff}.card strong{display:block;font-size:32px;line-height:1.3;letter-spacing:-1px}.card span{font-size:13px;color:var(--muted)}.card.changed strong{color:var(--orange)}.card.unavailable strong{color:var(--red)}.explain{background:#eaf0e6;border-left:3px solid var(--green);padding:15px 18px;border-radius:0 8px 8px 0;font-size:13px}.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:26px 0 12px;align-items:center}.toolbar input{flex:1;min-width:200px}.toolbar input,.toolbar select,.toolbar button{padding:9px 12px;border:1px solid #c9d6ce;border-radius:7px;background:white;color:var(--ink)}.toolbar button{background:var(--green);color:#fff;border-color:var(--green)}.results-meta{display:flex;justify-content:space-between;gap:12px;font-size:12px;color:var(--muted);margin:9px 0}.list{display:grid;gap:10px}details.record{border:1px solid var(--line);border-radius:9px;background:#fff;overflow:hidden}details.record>summary{list-style:none;display:grid;grid-template-columns:110px minmax(0,1fr) 180px 85px;gap:14px;align-items:center;cursor:pointer;padding:17px 18px}details.record>summary::-webkit-details-marker{display:none}details.record>summary:after{content:'＋';font-size:20px;text-align:right;color:var(--muted)}details[open].record>summary:after{content:'−'}details.record>summary{grid-template-columns:110px minmax(0,1fr) 180px 30px}.badge{font-size:12px;padding:3px 9px;display:inline-block;border-radius:5px;white-space:nowrap;width:fit-content}.badge.changed{background:#fff0df;color:var(--orange)}.badge.unchanged{background:#e4f0e8;color:var(--green)}.badge.observed{background:#e8eff8;color:var(--blue)}.badge.unavailable{background:#f8e9ec;color:var(--red)}.pkg{font-weight:650;overflow-wrap:anywhere}.sub{font-size:12px;font-weight:400;color:var(--muted)}.version{text-align:right;font-size:13px;overflow-wrap:anywhere}.body{padding:0 18px 20px;border-top:1px solid #eef1ec;font-size:13px}.body h3{margin:18px 0 8px;font-size:14px}.source{display:grid;grid-template-columns:100px minmax(0,1fr);gap:6px 15px;margin:16px 0}.source dt{color:var(--muted)}.source dd{margin:0;overflow-wrap:anywhere}code{font:12px ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}pre{font:12px/1.7 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f3;padding:12px;border-radius:6px;margin:0}.diff{display:grid;grid-template-columns:1fr 1fr;gap:10px}.diff-label{font-size:11px;color:var(--muted);margin-bottom:4px}.removed{color:var(--red)}.added{color:var(--green)}.issue{padding:10px 12px;background:#fbefef;border-radius:5px;color:var(--red);margin-top:14px}.empty{padding:40px;text-align:center;border:1px dashed var(--line);border-radius:8px}.notes{padding-left:18px;color:var(--muted)}footer{border-top:1px solid var(--line);margin-top:35px;padding-top:20px;font-size:12px;color:var(--muted)}footer p{max-width:950px}.downloads{display:flex;gap:18px;flex-wrap:wrap}.focus:focus-visible,button:focus-visible,summary:focus-visible,input:focus-visible,select:focus-visible,a:focus-visible{outline:3px solid #79a88a;outline-offset:3px}@media(max-width:760px){main{padding:24px 16px 45px}header{display:block}.edition{text-align:left;margin-top:15px}.cards{grid-template-columns:repeat(2,1fr);gap:9px}.cards .card:first-child{grid-column:span 2}.card{padding:12px 16px}.card strong{font-size:28px}details.record>summary{grid-template-columns:95px minmax(0,1fr) 22px;padding:13px 12px;gap:9px}.version{display:none}.body{padding:0 12px 15px}.diff{grid-template-columns:1fr}.source{grid-template-columns:1fr;gap:2px}.source dd{margin-bottom:8px}.toolbar input{width:100%;flex-basis:100%}}
</style></head><body><main>
<header><div><div class="eyebrow">Evidence Ledger / Public data audit</div><h1>让每一条修正，都有据可查。</h1><p class="muted">公开软件元数据巡检 · 原始来源留存 · 可离线复核</p></div><div class="edition"><span class="mode" id="mode"></span><p id="time"></p><span id="version"></span></div></header>
<section class="cards" aria-label="巡检统计" id="cards"></section>
<div class="explain" id="explain"></div>
<div class="toolbar"><input id="search" type="search" placeholder="搜索包名、记录编号、差异或错误…" aria-label="搜索记录"><select id="state" aria-label="按状态筛选"><option value="all">全部状态</option><option value="changed">发现差异</option><option value="unavailable">无法核实</option><option value="unchanged">断言一致</option><option value="observed">仅采集</option></select><select id="ecosystem" aria-label="按软件源筛选"><option value="all">全部软件源</option><option value="npm">npm</option><option value="pypi">PyPI</option></select><button id="export" type="button">导出当前结果 CSV</button></div>
<div class="results-meta"><span id="shown" role="status" aria-live="polite"></span><span>点击记录展开来源与差异</span></div><section class="list" id="list" aria-label="巡检记录"></section>
<footer><div class="downloads"><a href="report.json" download>完整 JSON</a><a href="corrections.csv" download>待审核修正表</a><a href="review.csv" download>全部记录 CSV</a><a href="input.csv" download>原始输入</a><a href="manifest.json" download>文件校验清单</a></div><p>差异表示“目录断言与所查询版本的发布者声明不同”，不等于安全漏洞、错误依赖或必须升级。仅采集表示没有提供比较断言；断言一致只覆盖所提供的字段。无法核实不能计为通过。许可证、仓库链接和依赖均来自注册表元数据，未经源码或法律审查。</p><p>本报告不安装或执行任何软件包，不自动修改上游数据，不发送追踪请求。校验清单用于发现文件损坏，并非数字签名；离线复核不能证明来源当前仍未变化。CSV 已处理常见表格公式注入前缀，原始值请以 JSON 为准。</p></footer>
</main><script type="application/json" id="data">__PAYLOAD__</script><script>__SCRIPT__</script></body></html>"""

SCRIPT = r""""use strict";
const report=JSON.parse(document.getElementById('data').textContent);
const labels={changed:'发现差异',unchanged:'断言一致',observed:'仅采集',unavailable:'无法核实'};
const $=id=>document.getElementById(id);
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const pretty=v=>typeof v==='string'?v:JSON.stringify(v,null,2);
$('mode').textContent=report.mode==='live'?'LIVE · 已留存来源':'OFFLINE · 已复核证据';
$('time').textContent='采集完成 '+report.finished_at.replace('T',' ').replace('Z',' UTC');
$('version').textContent='v'+report.tool_version+' / '+report.unique_sources+' 个独立查询';
for(const [key,label] of [['total','巡检记录'],['changed','发现差异 · 待审核'],['unavailable','来源或字段无法核实'],['unchanged','提供的断言一致'],['observed','仅采集 · 未作比较']]){const card=el('div',undefined,'card '+key);card.append(el('strong',report.summary[key]),el('span',label));$('cards').append(card);}
$('explain').textContent='本次检查 '+report.summary.total+' 条记录，其中 '+report.summary.compared+' 条提供了比较断言，共发现 '+report.summary.differences+' 项字段差异。所有差异需要审核；缺失来源和字段会单独显示。';
let visible=[];
function addDefinition(dl,key,value){dl.append(el('dt',key));const dd=el('dd');if(value instanceof Node)dd.append(value);else dd.textContent=value??'未声明';dl.append(dd);}
function safeLink(url,text){try{const u=new URL(url);if(u.protocol==='https:'&&['registry.npmjs.org','pypi.org'].includes(u.hostname)&&!u.username&&!u.password){const a=el('a',text||url);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a;}}catch{}return el('span',text||url);}
function recordView(r){const rec=r.record,obs=r.observed||{},receipt=r.receipts.at(-1)||{};const d=el('details',undefined,'record');const s=el('summary');s.append(el('span',labels[r.state],'badge '+r.state));const name=el('div',undefined,'pkg');name.append(el('div',rec.package),el('div',rec.ecosystem+' · '+rec.record_id,'sub'));s.append(name,el('div',(obs.version||'未取得版本')+(r.differences.length?' · '+r.differences.length+' 项差异':''),'version'));d.append(s);const body=el('div',undefined,'body');
if(r.error)body.append(el('p',r.error,'issue'));
for(const diff of r.differences){body.append(el('h3',diff.field));const grid=el('div',undefined,'diff');for(const [title,value] of [['目录原值',diff.expected],['来源观测值',diff.observed]]){const side=el('div');side.append(el('div',title,'diff-label'),el('pre',pretty(value)));grid.append(side);}body.append(grid);if(diff.added){const changes=el('div');for(const x of diff.removed)changes.append(el('div','− '+x,'removed'));for(const x of diff.added)changes.append(el('div','+ '+x,'added'));body.append(changes);}}
if(!r.differences.length&&r.observed){const text=r.state==='observed'?'此记录没有断言，仅采集元数据；不能据此判断目录正确。':'提供的断言与该来源一致；未提供的字段不参与判定。';body.append(el('p',text,'muted'));}
const dl=el('dl',undefined,'source');addDefinition(dl,'来源',safeLink(r.source_url));addDefinition(dl,'观测时间',receipt.fetched_at||'无');addDefinition(dl,'HTTP / 尝试',(receipt.http_status??'无响应')+' / '+r.receipts.length);addDefinition(dl,'SHA-256',el('code',receipt.sha256||'无'));addDefinition(dl,'查询选择器',rec.selector);addDefinition(dl,'依赖口径',rec.dependency_scope);if(rec.source_ref)addDefinition(dl,'目录出处',rec.source_ref);if(obs.repository)addDefinition(dl,'仓库声明',obs.repository);if(obs.license)addDefinition(dl,'许可证声明',obs.license);body.append(dl);
if(obs.notes?.length){const ul=el('ul',undefined,'notes');for(const note of obs.notes)ul.append(el('li',note));body.append(ul);}if(r.observed){const sub=el('details');sub.append(el('summary','查看规范化观测值'),el('pre',pretty(r.observed)));body.append(sub);}d.append(body);return d;}
function render(){const q=$('search').value.toLowerCase(),state=$('state').value,eco=$('ecosystem').value;visible=report.results.filter(r=>(state==='all'||r.state===state)&&(eco==='all'||r.record.ecosystem===eco)&&(!q||JSON.stringify(r).toLowerCase().includes(q)));$('list').replaceChildren();$('shown').textContent='显示 '+visible.length+' / '+report.results.length+' 条记录';if(!visible.length){$('list').append(el('div','没有符合筛选条件的记录。','empty'));return;}for(const r of visible)$('list').append(recordView(r));}
for(const id of ['search','state','ecosystem'])$(id).addEventListener('input',render);
function cell(v){let s=String(v??'');if(/^[ \t\r\n]*[=+\-@]/.test(s)||/^[\t\r\n]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';}
$('export').addEventListener('click',()=>{const rows=[['record_id','ecosystem','package','state','observed_version','source_url','fetched_at']];for(const r of visible)rows.push([r.record.record_id,r.record.ecosystem,r.record.package,r.state,r.observed?.version||'',r.source_url,r.receipts.at(-1)?.fetched_at||'']);const blob=new Blob(['\ufeff'+rows.map(row=>row.map(cell).join(',')).join('\r\n')+'\r\n'],{type:'text/csv;charset=utf-8'});const url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='evidence-ledger-filtered.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
render();"""

# Keep revision 1 byte-stable so already issued evidence bundles remain
# independently reproducible. Revision 2 bounds DOM size for large CSV batches.
TEMPLATE_V2 = TEMPLATE.replace(
    '<section class="list" id="list" aria-label="巡检记录"></section>',
    '<section class="list" id="list" aria-label="巡检记录"></section>'
    '<nav class="toolbar" aria-label="结果分页"><button id="previous" type="button">上一页</button>'
    '<span id="page-number" role="status" aria-live="polite"></span>'
    '<button id="next" type="button">下一页</button></nav>',
)
_OLD_RENDER = SCRIPT[SCRIPT.index("function render(){") : SCRIPT.index("function cell(v){")]
_NEW_RENDER = r"""let pageIndex=0;
const pageSize=50;
const searchIndex=report.results.map(r=>JSON.stringify(r).toLowerCase());
function render(){const q=$('search').value.toLowerCase(),state=$('state').value,eco=$('ecosystem').value;visible=report.results.filter((r,i)=>(state==='all'||r.state===state)&&(eco==='all'||r.record.ecosystem===eco)&&(!q||searchIndex[i].includes(q)));const pages=Math.max(1,Math.ceil(visible.length/pageSize));pageIndex=Math.max(0,Math.min(pageIndex,pages-1));$('list').replaceChildren();$('shown').textContent='匹配 '+visible.length+' / '+report.results.length+' 条记录';$('page-number').textContent='第 '+(pageIndex+1)+' / '+pages+' 页 · 每页最多 '+pageSize+' 条';$('previous').disabled=pageIndex===0;$('next').disabled=pageIndex>=pages-1;if(!visible.length){$('list').append(el('div','没有符合筛选条件的记录。','empty'));return;}for(const r of visible.slice(pageIndex*pageSize,(pageIndex+1)*pageSize))$('list').append(recordView(r));}
for(const id of ['search','state','ecosystem'])$(id).addEventListener('input',()=>{pageIndex=0;render();});
$('previous').addEventListener('click',()=>{pageIndex--;render();$('shown').scrollIntoView({block:'nearest'});});
$('next').addEventListener('click',()=>{pageIndex++;render();$('shown').scrollIntoView({block:'nearest'});});
"""
SCRIPT_V2 = SCRIPT.replace(_OLD_RENDER, _NEW_RENDER)
