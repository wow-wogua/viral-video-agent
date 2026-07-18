# P0-C UAPI Creator 数据源与正式 Gate（2026-07-18）

## 最终结论

UAPI Creator 数据源解决了原 P0-C 的账号投稿覆盖阻塞，但原冻结 P0-C 质量 Gate 仍未通过。最终停在 P0-C Gate Review，不进入 P0-D。

本轮没有修改 `competitor-score.p0.1`、`creator-qualification.p0.1`、`competitor-evaluation.p0.1`、原 20 个冻结关键词、人工标签、搜索候选范围、权重或资格门槛。旧 `20260716-183040` 失败基线和 `20260716-200338-recovery-canary` 负面证据完整保留。

## 数据源与授权边界

- Creator Provider：`uapi-creator.p0-c.1`。
- 来源：第三方 UAPI 的 B 站投稿和用户信息接口。
- `source_basis=third_party_development_api`。
- `authorization_status=development_only`。
- API Key 只由本地 `.env`/环境秘密注入，没有进入任务请求、日志、异常、fixture、公开文档或 Git。
- 本轮不证明生产授权、商业授权、稳定 SLA、全站覆盖、市场份额、增长趋势、营收、销量或转化。
- 当前只支持 B 站，数据是执行时快照。

## 5 MID connectivity canary

新 round：`20260718-092344-uapi-5-canary`，位于仓库外私有目录。

- 选择规则：`sha256(mid)` 升序，规则和目标集合哈希在请求前保存；失败后没有更换 MID。
- expected/resolved：5/5。
- Provider 正常响应：5/5。
- 可用于评分的投稿样本：3/5。
- 无公开投稿：2/5，保存为 partial + `no_public_uploads`，不是 Provider 故障。
- HTTP attempts：10；retry：0。
- 有效投稿：40；BVID、标题、发布时间、播放量和粉丝数完整率均为 100%。

该 round 证明 UAPI 连通、认证、字段规范化和无重试正常，但 5 MID 只作为 connectivity canary，不单独证明批量覆盖。

## 20 MID正式 canary

新 round：`20260718-092937-uapi-20-canary`，使用相同确定性规则，前 5 个样本保持不变。

- expected/resolved：20/20。
- 可用于评分的投稿样本：18/20，达到进入完整采集的最低条件。
- 无公开投稿：2/20。
- HTTP attempts：40；retry：0。
- 有效投稿：334。
- BVID、标题、发布时间完整率：100%，高于 95% 门槛。
- 播放量和粉丝数完整率：100%，高于 90% 目标。

20 MID canary 通过，因此没有进入 Playwright 兜底，也没有购买或接入供应商数据。

## 394 唯一 MID完整采集

正式新 round：`20260718-093647-uapi-full-gate`。

- expected/imported/covered：394/394/394。
- missing/unexpected：0/0；exact coverage：true。
- success：387；partial：7；failed/missing/not_attempted：0。
- 可用于评分的 Creator 样本：387/394，覆盖 98.22%，高于 90% 门槛。
- 7 个 partial 均为正常返回无公开投稿。
- 有效投稿：6913。
- BVID、标题、发布时间、播放量完整率：100%。
- 粉丝数完整率：100%。
- HTTP attempts：790；retry：2，均有限重试后恢复。
- 估算 UAPI 消耗：5 canary 40 + 20 canary 160 + full round 3160，合计约 3360 积分；实际账单以 UAPI 控制台为准。

完整覆盖通过数据 readiness Gate，才继续原冻结语义标签、评分和正式 Gate。

## 冻结标签、评分和资格结果

- 20 个关键词账号标签单元：400；本轮 LLM 调用 400，正式评分回读缓存 400。
- 搜索候选视频标签：relevant 405、irrelevant 95、uncertain 815。
- Creator 投稿标签：relevant 1981、irrelevant 4731、uncertain 320。
- 关键词隔离的 1198 个候选账号资格：`qualified_reference=48`、`emerging_candidate=21`、`excluded=269`、`discovery_only=860`。
- 最终选中 38 个位置，全部来自程序判定的 `qualified_reference`；没有用弱候选补满。
- Top 5 来源追溯、Evidence 和分数拆解检查全部通过。

## 正式 P0-C Gate

冻结公式版本：`competitor-evaluation.p0.1`。

| 指标 | 结果 |
|---|---:|
| 实际输出账号位置 | 38 |
| 人工 frozen qualified 命中 | 7 |
| 人工明确 excluded 误选 | 2 |
| unresolved 选中 | 29 |
| selected precision | 18.42% |
| strict Precision@5 | 33.33%（7/21 eligible slots） |
| 不相关账号误判率 | 5.26% |
| unresolved selection rate | 76.32% |
| eligible 输出覆盖 | 80.95% |
| 原始 5 槽位容量覆盖 | 38.00% |
| Retrieval Recall | 58.33% |
| 0 输出关键词 | 7/20 |
| shortfall keywords | 4 |

Gate 判断：

- Top 5 可追溯、分数可拆解：通过。
- 不相关账号误判率不高于 10%：通过。
- selected precision / strict Precision@5 不低于 0.8：未通过。
- 合格不足 5 时输出实际数量：通过。
- P0-C 总结论：failed。

## 类别结果

| 类别 | 输出 | selected precision | strict Precision@5 | 不相关误判率 | unresolved rate | eligible覆盖 | Retrieval Recall | abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| broad | 11 | 18.18% | 33.33% | 0.00% | 81.82% | 100.00% | 40.00% | 2/5 |
| vertical | 21 | 14.29% | 25.00% | 4.76% | 80.95% | 75.00% | 70.59% | 0/6 |
| brand | 5 | 40.00% | 66.67% | 20.00% | 40.00% | 66.67% | 75.00% | 1/4 |
| ambiguous | 1 | 0.00% | null | 0.00% | 100.00% | null | null | 2/3 |
| low_result | 0 | null | null | null | null | null | null | 2/2 |

## 保留的负面结果与下一阻塞

原失败基线的 HTTP 412、Provider `-352`、低覆盖和 9.52% strict Precision@5 没有删除或改写。新 UAPI round 证明 Creator 覆盖已不再是主要阻塞，但质量 Gate 仍失败：38 个选中位置中 29 个没有 frozen qualified/excluded 人工结论，unresolved rate 为 76.32%；另有 2 个明确 excluded 误选。

因此下一阻塞是账号级人工标签覆盖与资格/评分校准，而不是继续扩张数据源。应先补足中立的账号级人工复核，再在独立任务中判断是标签覆盖不足还是资格规则过宽；本任务不继续调权重、不针对关键词硬编码，也不进入 P0-D。

## 隔离与停止边界

- P0-C/Provider/API 定向：52 passed。
- P0-B 回归：43 passed。
- P0-A 回归：36 passed。
- 完整 Python：169 passed，仅 1 条既有 LangGraph PendingDeprecationWarning。
- Compose、Python 语法和 `git diff --check`：通过。
- 真实关键词、账号名、MID、逐视频标签、完整响应、LLM cache、SQLite 和详细评分只保存在仓库外私有 round。
- Git 只保存 Provider 代码、脱敏测试和公开汇总文档。
- 没有启用 Playwright、个人 Cookie、共享账号、代理池、验证码绕过或供应商购买。
- 无论未来如何校准，本轮已经按 P0-C Gate failed 停止；P0-D 仍被阻塞。
