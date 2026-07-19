# P0-C Creator Provider、竞品相关性与 Top 5

冻结 v1 版本：`content-intelligence.p0.1` / `creator-qualification.p0.1` / `competitor-score.p0.1`；历史 v3 评测版本：`creator-topic-assessment.p0.2` / `creator-qualification.p0.2` / `competitor-selection.p0.3`；Creator Provider：`bilibili-public-creator.p0-c.2` / `uapi-creator.p0-c.1` / `import-creator.p0-c.2`

## 范围和输入边界

P0-C 只消费带 `snapshot_revision=20260716_0003` 的新 crawl run。迁移前已被全局实体覆盖的旧 run 不能作为严格可复现输入。正式私有评测把 P0-B 冻结目录重放为新的 Import crawl run，保留原搜索来源、时间、Provider 版本和 `import_replay` 身份；它不是评测当天重新实时搜索。

完整链路：冻结搜索快照 → MID 聚合 → 固定顺序审计最多 20 个候选账号 → Creator Provider 最新最多 20 条公开投稿 → 逐视频相关性标签 → 程序评分和资格门禁 → 最多 5 个 `qualified_reference`。

人工补充账号不进入搜索候选池、程序评分或 Top 5，只用于私有评测的 Retrieval Recall 和 retrieval miss。没有 MID 的搜索视频保留在覆盖记录中，但不能伪造 MID 或升级为账号候选。

## Creator Provider

- Development：`bilibili-public-creator.p0-c.2`。只访问公开账号页相关接口，不读取个人 Cookie，不读取环境代理，不绕过登录、验证码、访问控制或风控；固定最新最多 20 条，记录观测时间、主页 URL、Provider 版本、30/90 天窗口和缺失原因。
- UAPI Development：`uapi-creator.p0-c.1`。第三方 development-only 数据源，只调用 `GET /api/v1/social/bilibili/archives` 和 `GET /api/v1/social/bilibili/userinfo`。API Key 只能通过 `UAPI_API_KEY` 或仓库外秘密配置注入，不能放进任务请求、日志、异常、fixture 或 Git。单并发，默认请求间隔 1.5 秒；429 遵循 `Retry-After`，timeout、connection 和 5xx 最多重试 2 次，认证错误与普通 4xx 不密集重试。
- Import：`creator-import.p0.1` / `import-creator.p0-c.2`。严格 JSON/CSV，未知字段、重复 MID、超过 20 条、状态与投稿不一致均拒绝；同时保存 import 身份和原始来源 Provider。可声明来源类型、授权状态、capture round、目标数量和目标集合哈希，并对当前候选集合执行 exact coverage 校验；声明不等于已经取得合同授权。
- Fixture：仅脱敏固定样例，自动化测试使用，不含真实私有关键词、MID 或账号名。

状态为 `success/partial/missing/failed/timeout/cancelled`。Provider 拿不到投稿时保留 missing 或失败状态；系统可以保存候选账号，但不得凭单条搜索视频升级为高置信度 Top 5。

Recovery 可靠性规则：HTTP 412 和 Provider `-352/-412/-401/-403` 不重试，并按账号最终结果计算连续风控；连续 3 次后打开断路，记录 15 分钟 cooldown 但不长等待或自动恢复。后续账号不发请求，保存 `missing + not_attempted_due_to_risk_control`。超时、连接错误、429、5xx 最多重试 2 次并记录 0.5/1 秒退避。每次 attempt 的分类、限频等待、退避、最终 circuit 状态进入私有 capture/import 审计，不保存响应正文或完整查询参数。

UAPI 在 2026-07-16 的官方公开页面中仍列出上述两个接口，二者均为 4 积分/次；一个账号正常采样通常调用投稿和用户信息各一次，即约 8 积分。官方公平使用页面说明限流动态调整，并建议平均不超过 40 次/分钟；状态页显示整体系统正常，但没有单独列出投稿接口监控。因此该 Provider 不能被描述为生产授权、商业授权或稳定 SLA。投稿接口当前可提供 BVID、标题、封面、时长、播放量和发布时间；用户信息接口可提供账号名与粉丝数。简介、标签、分区和多数互动字段拿不到时保持 null/missing，不调用额外接口补齐，也不由 LLM 猜测。

私有 canary 与完整采集使用 `sha256(mid)` 升序的确定性选择规则，规则和目标集合哈希在请求前写入新 round。5 MID 或 20 MID canary 失败后不得换样本；同 round 按账号原子 checkpoint 并幂等恢复，新 round 必须使用新目录。20 MID 至少 18 个可用、BVID/标题/发布时间完整率至少 95% 后，才允许考虑 394 MID 完整采集。

2026-07-18 真实验证结果：20 MID 为 18/20 可评分，关键字段完整率 100%；完整 394 MID 为 387/394 可评分、exact coverage 100%、关键字段完整率 100%。数据覆盖通过后，原冻结 v1 Gate 仍因 selected precision 18.42% 和 strict Precision@5 33.33% 失败；不相关误判率为 5.26%，但 unresolved selection rate 达 76.32%。随后完成的 53 项方案C人工审核验证了 HITL 产品辅助流程，但不能反向证明系统质量：纠正后的无偏 v2 Gate 只读取 pre-HITL 系统排序，selected precision 20.69%、strict Precision@5 28.57%、不相关误判率 3.45%，仍为 `failed`。因此不能继续用数据源扩张、人工真值重排或调权重包装为通过。详见 [P0-C UAPI Creator 数据源与正式 Gate](content-intelligence-p0c-uapi-gate-20260718.md)和 [P0-C v2 方案C](content-intelligence-p0c-scheme-c.md)。

私有批量采集每个账号后原子保存；同 round 恢复校验 Provider 版本和目标集合并跳过已有观测，断路 round 不会重新发请求。新 round 必须使用新的输出目录和 `capture_round_id`。完整 Recovery 记录见 [P0-C Creator Provider Recovery](content-intelligence-p0c-recovery-20260716.md)。

## 相关性 Schema 与 LLM 边界

每条搜索视频和账号投稿保存：`relevant/irrelevant/uncertain`、reason、confidence、Evidence IDs、labeler 和 labeler_version。账号级语义审计另存 generalist 判断、聚合/搬运/课程矩阵/内容农场/新闻转载/偶然命中风险和置信度。

LLM 只读取冻结意图与标题、简介、标签、分区和发布时间，输出语义标签和风险判断。候选数、比例、互动代理、分项、扣分、资格、总分、排序和 Top 5 全部由程序计算。LLM 不接收或补造粉丝数、播放量、互动、投稿数；输出缺项、重复 BVID、非法 JSON 或调用失败时，该账号标签降级为 `uncertain`，不能升级资格。

## `competitor-score.p0.1` 正向分项

总权重 100：

| 分项 | 权重 | 冻结公式 |
|---|---:|---|
| 搜索候选相关视频数 | 20 | `min(relevant_search_videos / 3, 1) * 20` |
| 近期相关内容占比 | 20 | `relevant / (relevant + irrelevant) * 20`，uncertain 不进分母 |
| 语义相关性 | 20 | `mean(relevant=confidence, irrelevant=1-confidence, uncertain=0.5) * 20` |
| 30/90 天活跃与频率 | 15 | `min(relevant_30d/4,1)*8 + min(relevant_90d/8,1)*7` |
| 互动表现 | 10 | `min(median((like+favorite+reply+danmaku)/view)/0.08,1)*10`；字段不完整的视频不进入样本 |
| 内容专注度 | 10 | `relevant / (relevant + irrelevant) * 10` |
| 样本充分度 | 5 | `min(decided_creator_uploads / 10, 1) * 5` |

每个分项保存 score、max_score、分子、分母、sample_size、公式和 missing_reason。缺失分项虽然数值为 0，但必须同时保存 missing_reason、降低置信度并触发明确扣分，不能静默把缺失当真实 0 或平均值。

## 扣分与置信度

扣分总和最多 20：单条命中且无持续性 5；近 90 天无相关投稿 5、弱持续性 2；样本不足 4、小样本 2；投稿列表缺失 5、partial 1～2；发布时间缺失 1；互动字段缺失 2；影响力字段缺失 1；聚合/矩阵风险 4、偶然命中风险 3；语义置信度低 3、中等 1.5。按固定顺序应用，达到 20 后停止增加。

置信度由账号样本状态 25%、已决标签覆盖 25%、20 条样本覆盖 20%、字段完整度 15%、语义置信度 15% 确定性计算。

## 资格和 Top 5

`creator-qualification.p0.1` 要求：最新最多 20 条中至少 3 条相关；近 90 天至少 3 条相关；宽泛词或 generalist 相关占比至少 20%，其他类别至少 30%；粉丝不少于 10000 或相关投稿播放中位数不少于 5000。低结果词必须使用另一个明确版本政策，因此本版本不会自动把低结果词账号升级为 qualified。

- `qualified_reference`：持续相关性和影响力均通过，可进入 Top 5。
- `emerging_candidate`：持续相关性通过但影响力不足，不进入 Top 5。
- `discovery_only`：样本、发布时间或语义置信度不足，不进入 Top 5。
- `excluded`：账号级审计确认不相关或存在明确聚合/矩阵风险。

稳定排序 `competitor-tie-break.p0.1`：总分降序 → 置信度降序 → 搜索相关视频数降序 → 90 天相关数降序 → 最佳搜索位置升序 → MID 字符序。输入顺序变化不影响结果。合格账号少于 5 个时只输出实际数量，并保存 shortfall_reason；允许为 0，禁止用弱相关账号补满。

## 冻结评测公式

公式版本：`competitor-evaluation.p0.1`。同一 MID 在不同关键词下独立判断。

- selected precision：选中且为人工 `qualified_reference` 的数量 / 实际选中数量；未被人工冻结为 qualified 的选中账号同样压低 precision。
- strict Precision@5：选中 qualified 数 / `min(5, 当前检索池中 qualified_reference 数)`；少输出造成的空槽位进入分母。没有可用 qualified 槽位时为 null，并单独报告 abstention。
- 不相关账号误判率：人工明确 excluded 且被选中的数量 / 实际选中数量。
- unresolved selection rate：没有 frozen qualified/excluded 判断却被选中的数量 / 实际选中数量，单独展示，不能隐藏在误判率之外。
- 输出数量覆盖：已填充的 eligible 槽位 / `min(5, 当前检索池中 qualified_reference 数)`；同时报告原始 `selected / (关键词数*5)` 容量覆盖。
- Retrieval Recall：检索到的 qualified_reference / 全部 frozen qualified_reference。
- abstention：实际输出 0 个；无 qualified、低结果词和有 qualified 但未输出分别保留原始结果。

按 broad、vertical、brand、ambiguous、low_result 分别统计。Gate 同时要求 selected precision 和 strict Precision@5 不低于 0.8、不相关账号误判率不高于 10%、分数可拆解、Top 5 来源可追溯。少输出不能通过隐藏覆盖不足来规避误判。

## 数据库、Worker 与 API

revision `20260716_0004` 新增 `creator_audits` 和 `creator_sample_videos`，并扩展 `competitor_scores` 与搜索视频标签来源。账号近期投稿不能放进原搜索候选表，因为它们不是搜索页结果、观测时间和 Provider 也不同；独立 per-run 表是保持冻结历史所需的最小结构。

同一 run 的 P0-C 结果在一个事务中替换自身 creator audits、sample videos、scores 和 crawl-run Evidence；不同 run 不互相覆盖。正常 `reports` 表不创建记录。`GET /jobs/{job_id}/competitors` 先校验任务所有权，返回 selected、全部候选评分、账号样本摘要、逐视频标签和 Evidence。旧 legacy LangGraph 与 `GET /jobs/{job_id}/search-snapshot` 保持兼容。

## 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_competitor_scoring.py tests\test_creator_providers.py tests\test_competitor_evaluation.py tests\test_competitor_integration.py tests\test_product_api.py
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_p0c_recovery.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_search_providers.py tests\test_search_snapshot_integration.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_intelligence_contracts.py tests\test_intelligence_metrics.py
.\.venv\Scripts\python.exe -m pytest -q
docker compose config --quiet
```

完整 20 关键词、真实账号样本、逐视频标签和评测结果只允许写入仓库外私有目录。当前人工基线只有 1 名真实复核者，不存在双人标注或标注者一致性证据；该限制不阻塞工程执行，但必须作为 Gate 保留项。

## P0-C v2 方案C兼容层

方案C在 v1 评分对象旁新增版本化账号—主题关系层，不覆盖 `competitor-score.p0.1`：

- `TopicSpec` 固定关键词意图、允许子主题和排除规则；离线评测不重新调用 LLM。
- Evidence Builder 确定性汇总搜索命中、账号投稿、相关/不相关/不确定数量、相关比例、30/90 天连续性、主页/公开信息、标题证据、字段缺失和 Evidence ID。
- 现有 `RelevanceLabeler` 只提供语义建议；兼容适配器读取旧缓存，缺少字段保持 unknown。
- Boundary Guard 检查单条命中、search-only、偶然命中、混合内容、样本不足、90 天连续性、低相关比例、聚合/搬运、Evidence 缺失和语义/规则冲突。
- `model_confidence` 与确定性 `system_confidence` 分开保存；后者由样本状态、标签覆盖、投稿覆盖、时间完整度、阈值 margin、连续性、冲突和 Evidence 完整度按固定权重计算。

v2 产品关系为 `core_competitor`、`adjacent_benchmark`、`occasional_hit`、`excluded`、`insufficient_evidence`。v2 Top 5 只在 `core_competitor` 内按 v1 基础分、系统置信度和稳定 tie-break 选择；相邻标杆单独展示，合格不足 5 个时不补位。P0-C v2 不包含代表视频、ASR、确定性商业指标或正常报告，详见 [P0-C v2 方案C](content-intelligence-p0c-scheme-c.md)。

质量 Gate 与 HITL 产品辅助输出必须分离：无偏 Gate 的资格、排序和 Top 5 不接受 `qualified_reference`、`excluded` 或新人工审核标签，冻结标签只在结果固定后用于计算评测指标；HITL 辅助输出可以应用人工 relevance / specialization / role overlay，并可复用冻结状态，但必须使用 `hitl-assisted-*` 命名并声明不具备无偏 Gate 资格。当前真实人工审核人数为 `reviewer_count=1`，53/53 已完成；HITL 辅助诊断为 selected precision 50.00%、strict Precision@5 100.00%、不相关误判率 0.00%，这些数值因人工标签参与资格和排序而不能作为质量通过证据。P0-D 继续阻塞。

## P0-C v3 与分层架构实验最终冻结

v3 不覆盖 v1 评分或 v2 关系文件。`creator-topic-assessment.p0.2` 把 System Prediction 和 Qualification Policy 结构化分开；`creator-qualification.p0.2` 要求 model confidence ≥0.85、至少 10 个已决投稿、5 个相关投稿、相关比例 ≥60%、90 天至少 3 个且 30 天至少 1 个相关投稿，并保留影响力、Evidence 和聚合/服务/generalist 边界。`competitor-selection.p0.3` 仍只在 core 内使用稳定旧排序，不接受人工 preference。

53 项开发集上的一次校准只用于形成候选，不是最终 Gate。随后完成的新盲评 selected precision 为 57.14%、strict Precision@5 为 80.00%、不相关误判率为 14.29%，14/20 关键词零输出，因此 v3 Gate 为 `failed`。

总控另外授权的一次分层架构实验只使用 97 项 development set，没有生成第二轮 holdout。账号 relevance 与 role 有局部改善，但 specialization 与 qualification 退化；最终 selected precision 69.23%、strict Precision@5 50.00%、不相关误判率 7.69%、output coverage 66.67%，selected count 为 13，14/20 关键词 abstain。这些不是最终线上指标，不能通过减少输出来包装质量达标。

该架构候选状态为 `architecture_candidate_invalid_stop`，没有 architecture freeze，也没有采用为运行时代码。失败源码只保存在本地归档分支和仓库外 Bundle，未推送 GitHub。P0-C 正式冻结；P0-D、P0-E 均未开始。详见 [P0-C v3 记录](content-intelligence-p0c-v3.md)和[分层架构失败实验说明](content-intelligence-p0c-architecture-repair.md)。
