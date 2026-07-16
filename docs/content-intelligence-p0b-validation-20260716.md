# P0-B 验证记录（2026-07-16）

## 结论

P0-B Gate 候选：**带保留通过**。

书面最小 Gate 已达到：20/20 关键词均至少有 1 页成功响应，所有任务最多请求 5 页，页级覆盖字段、BVID 去重和 MID 去重验证均为 100%。但 Development Provider 仍受 B 站风控和后续页 HTML 可解析性影响，不能描述为稳定生产数据源。

本记录不授权进入 P0-C；仍需总控只读复核。

## 自动化测试

- P0-B 定向：`35 passed`。覆盖 Provider 能力、1～5 页边界、第 6 页不请求、success/empty/failed/timeout/cancelled、部分成功、有限重试/退避、取消、重复 BVID/MID、无 MID、缺失字段、JSON/CSV Import 校验、数据库逐页快照、幂等、API 所有权和 0 页成功不产报告。
- P0-A 契约与指标回归：`36 passed`。
- 完整 Python：`121 passed`，仅有 1 条既有 LangGraph PendingDeprecationWarning。
- `docker compose config --quiet`：通过。
- 未修改前端或 migration，因此本轮不新增前端构建或 downgrade/upgrade 操作。

## 20 关键词真实低频验证

更正后的正式 Gate 候选证据保存在仓库外 `p0-b/20260716-143138/`，完整关键词、原始公开响应和人工对照未进入 Git。

- 20/20 关键词至少 1 页成功：100%。
- 请求页数：20 个任务均请求最多 5 页，共 100 页。
- 页状态：60 `success`、40 `failed`；无 `empty`、`timeout` 或 `cancelled`。
- 10 个关键词为 5/5 页成功；10 个关键词为 1/5 页成功并正确标记 `partial`。
- 50 页触发 `BILIBILI_CHALLENGE` 后尝试一次公开搜索 HTML 回退；其中 10 页回退成功，40 页因后续页没有可解析搜索卡片而记录 `HTML_RESULT_PARSE_FAILED`。
- 页级必需字段完整率：100%。
- BVID 去重验证：100%；MID 去重验证：100%。
- 与前一日人工公开搜索 Top 20 的重合率基线：183/400，45.75%。该数字只表示两个执行时快照的重合，不是召回率、市场覆盖率或质量 Gate。
- Import Provider 使用同一仓库外人工快照完成 20/20 稳定回退验证：100%。

## 纠错记录

首轮目录 `p0-b/20260716-141915/` 将仅含 `v_voucher` 的风控响应误记为 `empty`。复核响应结构后已修复：只有明确存在空 `result` 列表才是 `empty`；风控挑战和缺少结果列表均记为失败，并新增固定响应回归测试。首轮证据保留用于审计，不作为 Gate 结论依据。

## 真实性边界与保留项

- 当前是任务执行时公开搜索快照，不是全站数据。
- Development Provider 不需要个人 Cookie，但也没有生产商业授权或稳定 SLA。
- 40/100 页失败说明多页覆盖仍不稳定；不能把“20/20 至少一页成功”表述为“100 页全部成功”。
- 45.75% Top 20 重合率只建立动态基线，没有设定或达到 P0-C Precision@5/Recall Gate。
- P0-B 不生成 Top 5、代表视频、指标或 `IntelligenceReport`，也没有公开部署。
- 总控复核时应重点检查 Provider 风控分类、HTML 回退失败语义、部分成功查询、Import 数据权利和是否接受当前多页覆盖保留项。
