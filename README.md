# Evidence Ledger

把公开软件目录中的版本、依赖、仓库和许可证声明，与 npm / PyPI 的发布者元数据逐项核对。每次查询保留原始响应、采集时间和 SHA-256，输出可离线打开的中文报告和待审核 CSV。

**这是目录维护工具，不是漏洞扫描器、依赖解析器或自动升级工具。** 它不会下载、安装或执行软件包，不会修改上游目录，不要求 API 密钥。差异是审核线索，不是判错结论。

## 先看实际成果

- `artifacts/catalog-reviewed/report.html`：固定提交版本的 Chain.Love 目录样本，24 条记录；14 条存在依赖声明差异、10 条一致。全部原始来源已留存。
- `artifacts/maintenance-pilot/index.html`：同一批来源的多轮巡检记录；只有已完成的轮次才算实际采集，运行状态以页面为准。
- `docs/CASE-STUDY.zh-CN.md`：逐条审核、可选 peer 依赖边界、已有 PR 和哪些发现不算新贡献。
- `artifacts/quickstart/report.html`：npm / PyPI 双来源采集示例。没有提供目录断言，因此只记为“仅采集”。

原始来源属于发布者声明，不能证明包内容安全、可安装或许可证适合某种商业用途。历史快照不能代表未来状态。

## 不想输入命令：本地网页工作台

macOS 可双击 `启动工作台.command`，或执行：

```sh
python3 run.py serve --out runs/workbench --example examples/chain-love-npm.csv --open
```

它会打开本地网页，可选 CSV 或粘贴内容，再点击运行。仅监听 `127.0.0.1`，不是公开服务；使用随机端口、同源检查和会话令牌。网页每批最多 2 MiB / 500 条，最多三个排队或运行中的任务，不安装系统服务。原始目录断言不发送到注册表；仅查询包名和版本选择器。停止终端中的进程后结束工作台，已经保存的报告仍可离线打开。

## 直接运行：不需要 pip install

需要 Python 3.9 或更新版本。在 macOS / Linux：

```sh
cd /path/to/evidence-ledger
python3 run.py audit examples/quickstart.csv --out runs/my-first-audit
open runs/my-first-audit/report.html       # macOS
python3 run.py verify runs/my-first-audit
```

Windows 或不方便运行 shell 脚本时，在项目目录设置 `PYTHONPATH=src`，再运行：

```sh
python -m evidence_ledger audit examples/quickstart.csv --out runs/my-first-audit
python -m evidence_ledger verify runs/my-first-audit
```

输出目录必须是新目录，避免覆盖旧证据。`verify` **完全离线**，会核对文件清单、原始响应哈希、输入身份、规范化结果、汇总以及 HTML/CSV 导出的一致性。它检测损坏和内部不一致，不提供数字签名或可信时间戳。攻击者同时重写全部来源与清单时，不能据此证明来源真实。

也可以选择安装 CLI：

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install .
evidence-ledger --help
```

运行时无第三方依赖；打包安装时使用 setuptools。

## 输入 CSV

必填三列：`record_id,ecosystem,package`。可选列如下：

| 列 | 含义 |
|---|---|
| `record_id` | 唯一、稳定的记录编号，不能重复 |
| `ecosystem` | `npm` 或 `pypi` |
| `package` | 精确包名；PyPI 按其名称规范统一 `-_.` 和大小写 |
| `selector` | `latest`（默认）或具体发布版本；不接受范围、URL、自定义标签 |
| `expected_version` | 目录中需要核对的版本；留空不比较 |
| `expected_license` | 需要核对的许可证声明字符串；留空不比较 |
| `expected_repository` | 仓库声明；只做有限的传输/末尾 `.git` 规范化，不跟随仓库跳转 |
| `expected_dependencies` | JSON 字符串数组；留空不比较，`[]` 明确断言没有依赖 |
| `dependency_scope` | npm：`runtime`、`runtime+peer`（默认）、`runtime+peer+optional`；PyPI：`requires-dist` |
| `source_ref` | 目录出处和人工审核说明；原样作为文本展示，不请求该链接 |

npm 依赖格式为 `name@requirement`，包括 scoped 包，例如 `@scope/name@^1.2.0`。只比较直接声明，排除开发和传递依赖。不同组中相同包的不同要求不会被覆盖，两个字符串都保留。`runtime+peer` **包含可选 peer 声明**，不意味着它们都是必装运行依赖；原始响应包含 `peerDependenciesMeta`，审核时必须检查。

PyPI 依赖是 `requires_dist` 原始要求字符串，保留环境标记和 extras，不做版本兼容性求解或 PEP 508 语义等价判断。仅格式不同也可能产生文本差异。PyPI 缺少 SPDX 表达式时，仅在 legacy license 是简短单行字符串时使用它；缺失不表示“无许可证”。不会把任意 Home Page 猜成代码仓库。

比较是**字符串/集合一致性检查**，不是 semver 包含关系判断。例如 `^1.0.0` 和 `>=1.0.0 <2.0.0` 不会自动判为等价。

## 四种结果

| 状态 | 判定 |
|---|---|
| `changed` / 发现差异 | 至少一个断言不同，且预期字段均可核实 |
| `unchanged` / 断言一致 | 所有提供的断言一致；未提供的字段不参与判断 |
| `observed` / 仅采集 | 元数据有效，但输入没有提供比较断言 |
| `unavailable` / 无法核实 | 请求、格式、身份或预期字段无法核实；绝不会当作通过 |

部分字段无法核实时，已核实的差异仍会保留，但整条记录记为 `unavailable`。HTTP 200 本身不算通过；空对象、错误页面、错误包名/指定版本、非法 JSON、重复 JSON 键、超限响应都会失败。

## 输出结构

```text
run/
  input.csv                 原始输入
  report.json               完整机器可读结果
  report.html               可搜索、筛选、展开的独立中文报告
  review.csv                每条记录的状态和来源
  corrections.csv           每项差异的原值、观测值、版本、时间和证据哈希
  manifest.json             SHA-256 文件清单
  evidence/<sha256>.json     原始响应体，包括失败响应（扩展名不保证内容是有效 JSON）
```

CSV 对常见公式注入前缀添加 `'`；需要原始值时使用 JSON。修正表所有项目初始为 `review_required`，不会自动应用。文件清单是完整性辅助，不是认证签名。超限或中途断开的响应会明确标记，不会把截断内容当成完整来源。

## 持续维护和离线对比

```sh
# 前台运行一小时，每 15 分钟一轮；不安装系统定时任务
python3 run.py watch examples/maintenance-pilot.csv \
  --out runs/one-hour-pilot --duration 3600 --interval 900

# 两个已保存的来源快照，离线比较
python3 run.py diff runs/day-1 runs/day-2 > changes.json

# 核对多轮历史；结束后可封存索引与各轮证据清单的关联
python3 run.py verify-history runs/one-hour-pilot
python3 run.py seal-history runs/one-hour-pilot
```

`watch` 冻结开始时的输入，立即执行首轮，后续按间隔运行；错过的时间槽会跳过，不补发请求。截止时间后不再启动新轮次，已经在进行的请求可能在截止时间后完成。`--timeout` 是每次请求的 socket 超时，不是整个批次的硬截止。Ctrl-C 会记录为 `interrupted`；进程意外退出时，页面可能保留 `running`，应结合最后更新时间判断，不能据此认定仍在工作。

两轮之间区分 `source_changed`、`unchanged_verified`、`unavailable`、`recovered`、`configuration_changed`、`record_added`、`record_removed`。即使来源没变，目录仍可能与来源有差异，所以“目录差异数”和“本轮来源变化”分别统计。

## 退出码与边界

- `0`：完成；默认允许存在待审核差异。
- `1`：使用 `audit --fail-on-change` 且发现差异。
- `2`：至少一条记录/一次巡检无法核实。
- `3`：输入、文件或配置错误；已有输出不会覆盖。
- `130`：用户中断。

仅请求 `https://registry.npmjs.org` 和 `https://pypi.org`，不发送账户凭据、Cookie 或环境代理，不跟随 HTTP 跳转。默认 4 个并发、一次短重试；429 的长 `Retry-After` 不会被忽略并立即重试。每个响应上限 16 MiB，每轮原始证据上限 256 MiB、规范化结果估算上限 64 MiB，输入上限 8 MiB / 10,000 条记录。来源按有限并发取回和归档，不把所有原始响应留在内存中。报告每页只渲染 50 条；大报告的嵌入 JSON 仍会占用浏览器内存，建议实际服务按几十到数百条分批。

## 测试

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

包含故障注入、身份/格式验证、证据篡改与语义复算、原子输出、CSV/HTML 注入处理、离线无网络验证和有截止时间的持续巡检。测试不是对所有注册表边缘情况的保证，具体实测记录见 `docs/VALIDATION.md`。

## 来源与许可

- [npm Registry API](https://github.com/npm/registry/blob/main/docs/REGISTRY-API.md)
- [npm package.json 与依赖分类](https://docs.npmjs.com/cli/v11/configuring-npm/package-json/)
- [PyPI JSON API](https://docs.pypi.org/api/json/)
- [Chain.Love SDK 目录规则](https://github.com/Chain-Love/chain-love/wiki/SDKs)

工具代码采用 MIT。Chain.Love 原始目录、映射派生输入和包含其断言的报告数据保留 **CC BY-SA 4.0**；详见 `NOTICE.md`。发布者原始元数据和项目清单的权利归各自权利人；不要把顶层代码许可误认为授予第三方材料的额外权利。

由 Felix 的 AI 助手完成开发和来源审核；不声称有真人审计、不虚构客户、节省金额或收入。
