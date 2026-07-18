# P0-C Creator 数据源收口（2026-07-16）

## 2026-07-16 工程结论

阶段 A 的 UAPI Creator Provider 工程接入和 MockTransport 自动化已经完成；真实 5 MID 与 20 MID canary 尚未执行，原因是本地尚未确认 `UAPI_API_KEY`。原 `20260716-183040` 失败基线和 `20260716-200338-recovery-canary` Recovery 证据保持不变，P0-C Gate 仍未通过，不能进入 P0-D。

本次没有修改 `competitor-score.p0.1`、`creator-qualification.p0.1`、`competitor-evaluation.p0.1`、冻结关键词、人工标签或候选范围。

## 官方资料核验

2026-07-16 核验的官方公开页面：

- `GET /api/v1/social/bilibili/archives`：按 MID 获取投稿，默认/本任务固定 `ps=20`、`pn=1`、`orderby=pubdate`；公开响应字段包含 BVID、标题、封面、时长、播放量和发布时间。
- `GET /api/v1/social/bilibili/userinfo`：按 UID 获取公开账号信息；公开响应字段包含 MID、账号名和粉丝数。
- 两个接口在当前价格表均为 4 积分/次；一个账号正常采样通常需要两次调用。
- 认证示例使用 `Authorization: Bearer <API Key>`。
- 公平使用规则为动态限流，官方建议平均不超过 40 次/分钟；429/503 可携带 `Retry-After`。
- 状态页显示整体系统正常，但没有单独列出投稿接口监控，不能据此承诺投稿接口 SLA。

官方页面没有提供生产商业授权、缓存/衍生报告权利或稳定 SLA 的书面证明。因此 UAPI 只标记为第三方 `development_only`，P0-C 通过也不等于生产或商业授权。

## 实现边界

`uapi-creator.p0-c.1`：

- 只调用投稿和用户信息两个 P0-C 必需接口，不调用视频详情、评论或其他接口补字段。
- API Key 只从 `UAPI_API_KEY` 或仓库外秘密配置注入；任务 API 不接受或保存 Key。
- 不记录认证头、响应正文或 Key；审计只保存操作、attempt、分类、HTTP 状态、限频等待、退避、来源 URL、observed_at 和 raw hash。
- 单并发，默认最小间隔 1.5 秒。
- 429 优先遵循 `Retry-After`；timeout、connection 和 5xx 最多有限重试 2 次；401/403、404 和普通 4xx 不密集重试。
- 投稿字段规范化为现有 `CreatorSample` / `CreatorVideo` 契约；简介、标签、分区、like、coin、favorite、reply、share、danmaku 拿不到时保持 null/missing。
- 用户信息失败但投稿可用时保存 partial；缺少 Key 时不发网络请求并保存明确认证缺失；404 保存 missing；取消保存 cancelled。

私有 capture 流程继续使用仓库外新 round、逐账号原子 checkpoint、同 round 幂等、新 round 隔离和 exact coverage。canary 目标按 `sha256(mid)` 升序固定，选择规则与目标集合哈希在请求前保存，失败后不得换 MID。

## 验证状态

MockTransport 已覆盖：success、partial、missing、缺少认证、401/403/普通 4xx 不重试、429/Retry-After、timeout、connection、5xx 有限重试、取消、单并发、字段规范化、Provider 来源和 development-only 声明、Key 不进入输出，以及 UAPI round 的 checkpoint、幂等恢复、字段完整率和新 round 隔离。

- P0-C/Provider/API 定向：51 passed。
- P0-B 回归：43 passed。
- P0-A 回归：36 passed。
- 完整 Python：168 passed，仅 1 条既有 LangGraph PendingDeprecationWarning。
- `docker compose config --quiet`、`git diff --check` 和 Python 语法检查：通过。

真实执行顺序保持不变：

1. 新目录执行固定 5 MID connectivity canary。
2. 5 MID 没有暴露不可接受的数据条款、认证或稳定性问题后，新目录执行固定 20 MID canary。
3. 只有至少 18/20 可用，且 BVID、标题、发布时间完整率至少 95%，才允许考虑 394 唯一 MID 完整采集。
4. 完整覆盖建议达到 90% 以上才重跑原冻结 P0-C Gate。

若 UAPI 20 MID 不足 18 个可用，才进入用户授权 Playwright 本地采集；若组合覆盖仍不足，再由用户决定是否使用有书面授权的供应商或官方导出。不得自动购买数据，也不得使用共享账号、Cookie、代理池或验证码绕过。

## 真实性边界

- 当前只支持 B 站。
- 数据是执行时快照，不是全站穷举。
- 样本份额不是市场份额，第一次运行不能证明增长趋势。
- 不证明营收、销量、转化或商业效果。
- UAPI 是第三方 development-only 数据源。
- 后续 Playwright 如启用，只能是用户主动授权的本地开发采集，用户不需要向系统提供 Cookie 字符串。
- 无论 Gate 通过或失败，都必须停在 P0-C Gate Review。

## 2026-07-18 续跑结果

用户在本地完成 UAPI Key 配置后，严格按 5 MID → 20 MID → 394 MID 顺序执行：

- 5 MID：5/5 Provider 正常响应，3/5 有投稿样本，2/5 无公开投稿，10 attempts、0 retry。
- 20 MID：18/20 有可评分投稿，334 条投稿关键字段完整率 100%，40 attempts、0 retry，达到完整采集条件。
- 394 MID：exact coverage 394/394，387 个可评分、7 个无公开投稿，可用覆盖 98.22%；6913 条投稿关键字段完整率 100%，790 attempts、2 retry。

Creator 覆盖已解决，但正式冻结 Gate 仍 failed：selected precision 18.42%、strict Precision@5 33.33%、不相关误判率 5.26%、unresolved selection rate 76.32%。下一阻塞改为账号级人工标签覆盖与资格/评分校准；本任务没有调权重，也没有进入 P0-D。完整记录见 [P0-C UAPI Creator 数据源与正式 Gate](content-intelligence-p0c-uapi-gate-20260718.md)。
