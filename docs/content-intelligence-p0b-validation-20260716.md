# P0-B 验证记录（2026-07-16）

## 结论

P0-B 收口 Gate 候选：**通过**；Development Provider 的生产授权和多页稳定性仍保留为后续边界。

书面最小 Gate 已达到：20/20 关键词均至少有 1 页成功响应，所有任务最多请求 5 页，页级覆盖字段完整；BVID/MID 去重约束已通过结构检查和固定样例验证。该结论不是对所有线上原始数据的独立准确率证明。Development Provider 仍受 B 站风控和后续页 HTML 可解析性影响，不能描述为稳定生产数据源。

本记录不授权进入 P0-C；仍需总控只读复核。

## 自动化测试

- P0-B 定向：`40 passed`，命令包含 `test_search_providers.py`、`test_search_snapshot_integration.py` 和 `test_product_api.py`。除原有 Provider、分页、状态、Import、幂等、API 所有权和不产报告覆盖外，新增跨任务同 BVID、跨任务同 MID、同任务重试替换、partial 隔离、删除级联和 `attempt_state=previous_attempt` 回归。
- P0-A 契约与指标回归：`36 passed`。
- 完整 Python：`126 passed`，仅有 1 条既有 LangGraph PendingDeprecationWarning。
- `docker compose config --quiet`：通过。
- Alembic `20260716_0003`：临时 PostgreSQL 16 tmpfs 容器中完成 upgrade/current/check、downgrade 到 `20260715_0002`、旧结构移除检查、脱敏旧数据回填、re-upgrade/current/check；两次 `alembic check` 均无新增操作。未连接或修改正式数据库和正式卷。

## 不可变快照收口

原实现的 `crawl_run_videos` 只保存 BVID、页码和排名，查询历史快照时再关联全局 `videos`、`creators`。后续任务命中相同 BVID/MID 后会更新全局行，导致旧任务查询出新标题、指标、创作者和观测时间。

收口后：

- `videos`、`creators` 继续作为按 BVID/MID 归一化的最新实体。
- `crawl_run_videos` 保存完整 per-run 视频观测；新增 `crawl_run_creators` 保存完整 per-run 创作者观测。
- `GET /jobs/{job_id}/search-snapshot` 只读取目标 crawl run 的页和 observation，不再从全局最新实体拼装历史快照。
- 同一 Job 重试复用 crawl run 并原子替换自身 observation；不同 Job 相互隔离。
- 删除 Job/crawl run 会清理自己的 observation，不删除全局实体或其他任务的数据。

迁移只能把 revision `20260716_0003` 执行时仍保存在全局实体中的值回填给旧关联；如果旧任务在迁移前已被后续任务覆盖，原始差异无法凭数据库现状逆向恢复。因此 P0-C 不应把 pre-`20260716_0003` 历史行当作严格可复现输入；应从迁移后的新 crawl run 开始消费冻结候选池。该边界不阻塞基于新快照进入 P0-C，但需由总控重新审核放行。

脱敏 migration 和自动化验证日志保存在仓库外 `p0-b/20260716-164400-immutable-snapshot-gate/`，未提交原始搜索响应或私有人工基线。

## 20 关键词真实低频验证

更正后的正式 Gate 候选证据保存在仓库外 `p0-b/20260716-143138/`，完整关键词、原始公开响应和人工对照未进入 Git。

- 20/20 关键词至少 1 页成功：100%。
- 请求页数：20 个任务均请求最多 5 页，共 100 页。
- 页状态：60 `success`、40 `failed`；无 `empty`、`timeout` 或 `cancelled`。
- 10 个关键词为 5/5 页成功；10 个关键词为 1/5 页成功并正确标记 `partial`。
- 50 页触发 `BILIBILI_CHALLENGE` 后尝试一次公开搜索 HTML 回退；其中 10 页回退成功，40 页因后续页没有可解析搜索卡片而记录 `HTML_RESULT_PARSE_FAILED`。
- 页级必需字段完整率：100%。
- BVID/MID 去重结构与固定样例验证通过；这不是覆盖所有线上原始数据的独立准确率测量。
- 与前一日人工公开搜索 Top 20 的重合率基线：183/400，45.75%。该数字只表示两个执行时快照的重合，不是召回率、市场覆盖率或质量 Gate。
- Import Provider 使用同一仓库外人工快照完成 20/20 稳定回退验证：100%。

## 纠错记录

首轮目录 `p0-b/20260716-141915/` 将仅含 `v_voucher` 的风控响应误记为 `empty`。复核响应结构后已修复：只有明确存在空 `result` 列表才是 `empty`；风控挑战和缺少结果列表均记为失败，并新增固定响应回归测试。首轮证据保留用于审计，不作为 Gate 结论依据。

本次不可变快照收口没有修改 Development/Import Provider、HTML 回退、规范化或分页逻辑，因此没有重新触发 20×5 页公开搜索；正式 Provider 证据继续沿用 `p0-b/20260716-143138/`。

## 真实性边界与保留项

- 当前是任务执行时公开搜索快照，不是全站数据。
- Development Provider 不需要个人 Cookie，但也没有生产商业授权或稳定 SLA。
- 40/100 页失败说明多页覆盖仍不稳定；不能把“20/20 至少一页成功”表述为“100 页全部成功”。
- 45.75% Top 20 重合率只建立动态基线，没有设定或达到 P0-C Precision@5/Recall Gate。
- P0-B 不生成 Top 5、代表视频、指标或 `IntelligenceReport`，也没有公开部署。
- 总控复核时应重点检查 Provider 风控分类、HTML 回退失败语义、部分成功查询、Import 数据权利和是否接受当前多页覆盖保留项。
