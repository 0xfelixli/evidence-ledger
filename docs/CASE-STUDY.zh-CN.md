# 真实案例：24 条 SDK 目录记录的可复查巡检

这不是客户委托，也没有因此获得收入。目的在于验证：我们能否把一次手工修正，变成可以重复交付、解释清楚且保留证据的数据维护流程。

## 数据范围与复现

上游为 [Chain.Love](https://github.com/Chain-Love/chain-love)，固定提交 `09e5460c2e4697f6e0a4854f93e97efab5764c44` 的 `references/offers/sdks.csv`。保存的文件共 216 条记录，本次只检查其中 **24 条明确映射到 npm 的记录**，不声称审核了整份目录。

原始 CSV、来源 URL、提交信息、文件哈希和许可位于 `sources/chain-love/`。输入是 `examples/chain-love-npm.csv`。依赖比较口径固定为发布版本的 **runtime + peer**，排除开发、传递和 `optionalDependencies`，但包含声明为可选的 peer。因此必须结合下文解释，不能把所有差异都当成同一类错误。

```sh
python3 run.py audit examples/chain-love-npm.csv --out runs/catalog-check
python3 run.py verify runs/catalog-check
```

`artifacts/catalog-reviewed/` 保存了 2026-10-27 16:03 UTC 的实测结果：**24 条可核实，14 条依赖声明不同，10 条一致**。将来重跑可能变化，请以新报告中的时间和原始证据为准。

## 包名映射不靠猜

六条记录的上游 `actionButtons` 已有精确 npm 包链接；其余 18 条通过项目拥有的 GitHub 源码清单中 `name` 字段交叉核对。研究记录在 `sources/mapping-review/review.json`，映射明细在 `sources/chain-love/package-mapping.csv`。

开发分支的 package.json **只用于映射身份**，不用于证明发布版本的依赖；依赖全部取自 npm 发布版本响应。共享 monorepo 的不同包也分别检查名称。

开发期间曾把 Somnia Data Streams 错映射为 `@somnia-chain/data-streams`，得到 404。阅读项目官方安装说明后修正为 `@somnia-chain/streams`。该误映射只留在 `catalog-first` 的开发记录中，没有当作上游停服或目录缺陷，也不计入最终不可用数。这说明“先确认身份”本身是服务交付的一部分。

## 14 条差异逐项解释

| 目录记录 | 查询到的版本 | 差异概要 | 审核意见 |
|---|---|---|---|
| `algokit-subscriber-ts` | 3.4.0 | `algosdk` 要求从 `^3.7.0` 到 `^3.8.0` | 发布清单差异；已有相关刷新提案 #4036，应先核对是否覆盖 |
| `circle-bridge-kit` | 1.16.1 | 三个 Circle provider 包要求更新 | 精确 npm 链接支持映射；可作为待审核刷新候选，未证明没有重复 PR |
| `ens-js` | 5.2.7 | 新增 ensjs-abi/cborg，移除若干旧声明，并调整要求 | 跨版本较大，不能只凭文本差异认定旧目录错误；需确认目录想追踪的版本 |
| `iso-filecoin-react` | 2.2.1 | 更新 iso-filecoin / wallet adapter 要求 | 已在本任务前提交的 #4897 涉及此条；不算本次新贡献或新收入 |
| `iso-filecoin-wallets` | 1.3.1 | 移除两个不再声明的 Reown 包，调整六项要求 | 同上，已有 #4897；保留证据，不重复提交 |
| `pera-connect` | 1.9.0 | 当前清单还声明 `algosdk@^3.5.2` peer | peer 收录口径问题；不要说成新增加的必装 runtime 依赖 |
| `safe-api-kit` | 5.0.4 | protocol-kit 要求从 `^8.0.6` 到 `^8.0.8` | 发布清单差异；可作为刷新候选，未证明没有重复 PR |
| `safe-protocol-kit` | 8.0.10 | 两项 safe deployment 包要求更新 | optionalDependencies 单独保存但未并入比较，不隐去口径 |
| `safe-relay-kit` | 6.1.4 | protocol-kit 和 modules-deployments 要求更新 | 发布清单差异；可作为刷新候选，未证明没有重复 PR |
| `somnia-contracts-sdk` | 0.3.9 | 声明可选 peer `viem@^2.0.0` | 仅口径审核；不是所有用户都必须安装 viem 的证据 |
| `synapse-core` | 0.10.2 | 新增 commp-wasm，更新 ox | 已存在 Synapse 相关提案 #4034；先核对范围，不抢占或重复提交 |
| `synapse-react` | 0.5.1 | core/sdk 要求更新 | 同一项目已有刷新讨论；本次只是复现差异 |
| `synapse-sdk` | 2.0.2 | core 要求从 `^0.9.0` 到 `^0.10.0` | 已有相关 #4034；不是全新发现 |
| `viem` | 2.57.12 | ox 要求更新，另声明可选 peer TypeScript | ox 的文本差异与可选 peer 政策分开审核，不能一键接受整项建议 |

差异详情、原数组、当前数组及每一项增减位于 HTML 和 `corrections.csv`。上表是 AI 助手对来源的解释，没有冒充真人审计。

## 为什么没有直接提交 14 个修正

1. 上游没有给每条目录记录绑定一个明确的发布版本。这里证明的是“与查询到的版本不同”，不能证明目录作者承诺追踪的就是该版本。
2. peer 与 optional peer 的收录方式已有 [DBIP/PR 讨论](https://github.com/Chain-Love/chain-love/pull/4154)。本工具不替维护者决定 schema 政策。
3. 存在已有贡献，包括 [#4034](https://github.com/Chain-Love/chain-love/pull/4034)、[#4036](https://github.com/Chain-Love/chain-love/pull/4036) 和我们的旧 [#4897](https://github.com/Chain-Love/chain-love/pull/4897)。重复提交会给维护者增加负担。
4. GitHub 公共搜索在部分查询返回限流错误，查重不完整，已记录在 `sources/triage/search-status.json`。没有把“未查到”当成“没有”。
5. `latestKnownVersion`、`latestKnownReleaseDate`、`maintainer`、`license` 是上游自动化保留字段。本案例没有修改这些字段，也不生成自动填充补丁。

## 实际价值与尚未证明的部分

已经证明的：一次命令可以把 24 条目录断言转为带原始来源、字段级差异、失败状态和离线复核的审核包；同一份输入可以持续巡检，来源失效不冒充正常；npm 和 PyPI 的无断言采集也能运行。

尚未证明的：有人愿意付费、维护者接受全部建议、每条差异都该合并、节省了多少人工小时、产生了多少收入。没有将这些写成成果。

可出售的最小交付可以是“10 条约定记录的来源核验 + 修正候选表 + 证据包”。价格、字段口径、接受标准和更新频率需要双方约定，不能因为发过报价就声称成交。
