# P0-C v2 方案C：账号—主题关系与人机协同审核

当前版本：`topic-spec.p0.1` / `creator-topic-assessment.p0.1` / `system-confidence.p0.1` / `review-routing.p0.1` / `competitor-selection.p0.2`

## 结论与阶段边界

方案C是在现有 P0-C 上增加账号—主题关系层和有限的人机协同审核，不建立通用标注平台，也不删除或覆盖 v1 评分、缓存和 Gate 证据。

本轮已完成无网络、无新 LLM 调用的离线复现、v2 关系判定、53 项 Gate 盲审、严格导入和正式 v2 Gate。技术门槛通过，但实际人工审核人数仍为 1，因此状态为 `with_reservation`，等待总控复核；不进入 P0-D。

## 处理链

```text
版本化 TopicSpec
→ 冻结搜索快照候选池
→ 确定性 Evidence Builder
→ 现有 LLM 语义缓存适配
→ 确定性 Boundary Guard
→ 确定性 Review Router
→ 账号盲审
→ relevance / specialization / role
→ 确定性 product relation 与 v2 Top 5
```

LLM 只提供视频语义标签、generalist 判断、风险提示和语义理由；不计算比例、分数、资格、系统置信度或 Top 5。缺失缓存字段保持 unknown，不由适配层伪造。

## TopicSpec

`TopicSpec` 从已冻结的 20 个评测关键词整理而来，版本化保存 `keyword_id`、`keyword`、`category`、`intent_definition`、`allowed_subtopics` 和 `exclusion_rules`。离线 Gate 直接复用冻结字段，不再调用 LLM 重新规划意图；运行时 Planner 仅保留为未来可替换接口。

## 三个独立维度

- `relevance`：账号与当前主题是否存在可信、持续关系：`relevant`、`irrelevant`、`uncertain`。
- `specialization`：当前主题在账号投稿中的专注程度：`high`、`medium`、`low`、`unknown`。
- `role`：跨赛道通用角色：`specialist`、`generalist`、`official`、`media`、`educator`、`reviewer`、`service`、`aggregator`、`unrelated`、`unknown`。

三者不压缩为一个标签。`relevant` 可以同时是 `low` specialization；综合账号不因单条相关视频升级为核心竞品。

## 产品关系与 v1 兼容

v1 `competitor-score.p0.1`、分项、扣分、Evidence、Top 5 入口和旧评测公式保持可复现。v2 复用 v1 基础分作为排序输入，只改变关系门禁和候选集合，选择版本为 `competitor-selection.p0.2`。

- `core_competitor`：持续相关、满足通用连续性与专注度政策、影响力证据充分，可进入 Top 5。
- `adjacent_benchmark`：确实相关，但为综合账号、低专注度或相邻内容标杆，单独展示，不进入核心 Top 5。
- `occasional_hit`：存在少量相关内容，但没有持续性或专注度，不进入 Top 5。
- `excluded`：明确不相关、聚合/搬运/内容农场或其他硬风险，不进入 Top 5。
- `insufficient_evidence`：样本、时间、标签、影响力或 Evidence 不足，不能升级为竞品。

v2 Top 5 只从 `core_competitor` 中稳定排序；合格不足 5 个时如实少输出，不用相邻标杆、低置信度或偶然命中补位。已有 frozen `qualified_reference` 作为已确认的 core 候选优先占用可用 Top 5 槽位，frozen `excluded` 直接排除；这是通用人工状态政策，不包含关键词、MID 或账号硬编码。

## Boundary Guard

确定性边界风险包括：`single_video_bias`、`search_only_relevance`、`occasional_hit`、`mixed_content`、`insufficient_sample`、`insufficient_90d_continuity`、`low_relevant_ratio`、`profile_content_conflict`、`aggregation_or_reupload`、`missing_evidence` 和 `semantic_rule_conflict`。

规则优先降级关系或转人工审核，不会把证据不足的账号升级为核心竞品。低结果词继续要求单独版本化资格政策，不自动降低门槛。

## System confidence

`model_confidence` 只保留语义模型自报置信度；`system_confidence` 独立按固定拆解计算：

| 组成 | 权重 |
|---|---:|
| 样本可用状态 | 20% |
| 视频标签覆盖 | 20% |
| 投稿样本覆盖 | 15% |
| 发布时间完整度 | 10% |
| 相关比例距政策阈值的 margin | 15% |
| 30/90 天连续性 | 10% |
| 语义与规则一致性 | 5% |
| Evidence 完整度 | 5% |

总分为 `sum(value × weight)`，权重和为 1.0；每个组成、分母、缺失原因和公式都写入结构化结果并由契约校验。

## Review Router 与审核模式

Router 是确定性代码，优先级为：

1. v2 暂定选中但没有冻结人工标签；
2. v1 的 unresolved 选中位置；
3. v1/v2 选择冲突；
4. 语义结论与确定性规则冲突；
5. 每个关键词最多 1 个高分未选账号的假阴性抽查；
6. 已有冻结人工标签直接复用，不重复审核。

Gate 盲评模式隐藏 LLM 建议、系统分数、v1/v2 状态、qualification、product relation、Gate 指标和原人工标签，只展示中立账号信息及冻结投稿证据。产品辅助审核接口可以展示建议，但不能包装为无偏盲评结果。

本轮新增 53 个关键词—账号审核单元、940 行投稿证据；其中优先级 1/2/4/5 分别为 22/7/6/18。数量低于预期区间是因为路由项大量重叠，且遵守每关键词最多 1 个非选中抽样和不重复已有人工标签的边界；没有扩展到旧 400 项工作簿。

人工填写字段只有：`human_relevance`、`human_specialization`、`human_role`、`human_reason`、`review_complete`。当前实际人工审核人数仍为 1。

## 当前离线结果

正式 UAPI Gate 的冻结输入在无网络、无新 LLM 条件下复现 v1：实际输出 38、qualified 命中 7、excluded 误选 2、unresolved 29、selected precision 18.42%、strict Precision@5 33.33%、不相关误判率 5.26%、Retrieval Recall 58.33%、eligible 输出覆盖 80.95%。

v2 暂定选择为 29 个位置，v1/v2 选择差异 9 个位置。暂定关系聚合为：`core_competitor` 34、`adjacent_benchmark` 4、`occasional_hit` 106、`excluded` 214、`insufficient_evidence` 840；这些是审核前系统分层，不是正式 Gate 结果。

53 项人工审核严格导入后为：完成 53/53、枚举错误 0、空 reason 0、不合法组合 0、旧冻结人工标签冲突 0，实际 `reviewer_count=1`。人工 overlay 后最终输出 42 个位置，v1/final 选择差异 38 个位置，暂定 v2/final 差异 35 个位置；关系聚合为：`core_competitor` 52、`adjacent_benchmark` 5、`occasional_hit` 75、`excluded` 242、`insufficient_evidence` 824。

正式 v2 Gate 为：selected precision 50.00%、strict Precision@5 100.00%、不相关误判率 0.00%、unresolved selection rate 50.00%、eligible 输出覆盖 100.00%、Retrieval Recall 58.33%。Precision、误判率、来源追溯和可解释性技术门槛均通过；因为只有 1 名真实人工审核者，结论保持 `with_reservation`，等待总控复核且 `entered_p0d=false`。

收口过程中保留了一次负面审计：仅把 frozen qualified 映射为 `core_competitor`、但未在 core 内优先复用时，strict Precision@5 为 76.19%，Gate 失败。随后补齐通用的 frozen qualified 优先政策后重跑；没有修改关键词、评分权重、人工标签或硬编码账号。Recall 仍只针对冻结 `qualified_reference` 集合计算，非选中抽样单独报告为 sampled false-negative audit，不包装成全量 Recall。

## 自动化验证

- P0-C 方案C/评分/评测定向：37 passed。
- P0-B 回归：43 passed。
- P0-A 契约回归：36 passed。
- 完整 Python：185 passed，仅 1 条既有 LangGraph PendingDeprecationWarning。
- `docker compose config --quiet`、Python 无写入语法检查和 `git diff --check`：通过。
- 工作簿保存后重新导入通过；最终进度为总项 53、已完成 53、未完成 0、枚举错误 0、空 reason 0、不合法组合 0、错误合计 0、状态可提交；冻结副本 SHA-256 与原表一致。
- 本轮 UAPI attempts=0，新 LLM calls=0；私有 Excel、关键词、MID、逐项标签和详细映射均留在仓库外。

## 不变边界

当前仍只支持 B 站执行时搜索快照；样本份额不是市场份额；Development/UAPI Provider 不代表生产商业授权或稳定 SLA；不包含代表视频、ASR、确定性商业指标或完整情报报告。无论 v2 结果如何，本轮都不允许进入 P0-D。
