# P0-C 验证记录（2026-07-16）

## 结论

P0-C Gate 候选：**未通过**，因此停在 P0-C Gate Review，不进入 P0-D。

工程链路、分数拆解、来源追溯和缺失降级通过自动化验证；20 关键词真实评测未达到质量与覆盖 Gate。主要阻塞不是权重，而是 Development Creator Provider 在批量低频审计中受到公开接口风控：400 个“关键词×候选账号”审计位中只有 29 个取得投稿样本，371 个失败，其余 798 个检索候选位于固定 Top-20 审计范围之外并明确标记 missing。没有用单条搜索视频、弱相关账号或人工补充参考集填满 Top 5。

## 输入和真实性

- 搜索输入来自仓库外 P0-B 正式冻结目录的 Import replay，共 20 个新 crawl run、1323 条去重视频、1198 个按关键词隔离的候选账号观测。
- replay 保留原搜索来源、时间、Provider 版本、原 crawl run ID 和 `import_replay` 身份；不是 2026-07-16 晚间重新实时搜索。
- Creator 样本对每个关键词按固定通用顺序最多审计 20 个候选账号，共 400 个审计位、394 个唯一 MID；没有重新发起 20×5 页搜索。
- 完整账号名、MID、逐视频标签、LLM缓存、分项和人工对照只保存在仓库外私有目录。
- 当前人工基线为 1 名真实复核者，20/20 项 `reviewer_count=1`；没有双人标注或标注者一致性证据。

## 自动化验证

- P0-C 定向（评分、Creator Provider、评测公式、集成、Worker）：`24 passed`。
- P0-B Provider/快照/API 回归：`42 passed`。
- P0-A 契约与指标回归：`36 passed`。
- 完整 Python：`152 passed`，仅 1 条既有 LangGraph PendingDeprecationWarning。
- 迁移、Compose 和最终完整命令见本次 Gate 审计记录；P0-C 不修改前端。

## 20 关键词结果

冻结公式版本：`competitor-evaluation.p0.1`。

| 指标 | 结果 |
|---|---:|
| 实际输出账号 | 6 |
| 人工 qualified 命中 | 2 |
| selected precision | 33.33% |
| strict Precision@5 | 9.52%（2/21 eligible slots） |
| 人工明确不相关误判率 | 0.00% |
| unresolved selection rate | 66.67% |
| eligible 输出覆盖 | 14.29% |
| 原始 5 槽位容量覆盖 | 6.00% |
| Retrieval Recall | 58.33% |
| 0 输出关键词 | 18/20 |
| shortfall slots | 18 |

不相关误判率为 0 不能单独解释为质量通过：只有 6 个输出，其中 4 个没有 frozen qualified/excluded 人工结论，因此 selected precision、strict Precision@5、覆盖和 unresolved rate 同时显示失败。

## 类别结果

- broad：输出 6；selected precision 33.33%；strict Precision@5 33.33%；覆盖 50%；Retrieval Recall 40%；3/5 abstain。
- vertical：输出 0；strict Precision@5 0；Retrieval Recall 70.59%；6/6 abstain。
- brand：输出 0；strict Precision@5 0；Retrieval Recall 75%；4/4 abstain。
- ambiguous：输出 0；当前冻结文件没有可计算 eligible 槽位；3/3 abstain。
- low_result：输出 0；`creator-qualification.p0.1` 明确要求另一个低结果政策，不自动降门槛；2/2 abstain。

## Creator Provider 与负面结果

- 账号样本 `success=29`、`failed=371`、`missing=798`。
- 失败中 `HTTP 412=308`、Provider `-352=63`；均保留失败状态，没有伪装为空列表或补造投稿。
- 最终资格：`qualified_reference=6`、`emerging_candidate=4`、`excluded=17`、`discovery_only=1171`。
- 逐视频 LLM 标签：`relevant=186`、`irrelevant=267`、`uncertain=74`；标签器只输出语义判断，数值和总分由程序计算。
- 400 个关键词账号标签单元全部有缓存；本次续跑实际新增 374 次模型调用、命中 426 次缓存（包含正式评分阶段回读），没有打印 Key、Token 或完整请求。

## 校准决定

没有使用唯一一次规则/权重校准。错误分析显示主要失败来自账号投稿样本风控和人工判定覆盖，而不是某个通用分项权重导致的边界误差。在样本大量 missing 时调权重只会把单条搜索命中包装成高置信度竞品，违反资格政策。因此保存调整前后相同的完整结果，`calibration_cycles_used=0`，停止继续调参。

## Gate 判断

- Top 5 来源和账号样本追溯：通过。
- 分数拆解、缺失和程序边界：通过。
- Precision@5 ≥ 0.8：未通过。
- 不相关账号误判率 ≤ 10%：数值通过，但样本小且 unresolved 高，不能单独放行。
- 合格不足 5 时实际输出、不补满：通过。
- broad/vertical/brand/ambiguous/low_result 分类和负面结果：已保留。
- 双人标注一致性：没有证据，保留项。

P0-C Gate 最终为未通过，阻塞 P0-D。后续若总控决定继续，应先解决合法稳定的 Creator 数据来源或增加真实人工账号级复核，不能继续围绕当前 20 关键词反复调权重。

## Recovery Gate 补充（2026-07-16）

在不改变评分、资格、评测公式、关键词或人工标签的前提下，Creator Provider 已升级为 `bilibili-public-creator.p0-c.2`：增加 412/`-352` 风控分类、连续 3 次固定断路、断路后 `not_attempted_due_to_risk_control`、只针对 timeout/connection/429/5xx 的最多 2 次退避重试、逐 attempt 审计、逐账号原子 checkpoint、同 round 幂等恢复和新 round 隔离。Import Provider 增加来源/授权声明和候选集合 exact coverage 校验。

Recovery 自动化为 P0-C 定向 41 passed、P0-B 42 passed、P0-A 36 passed、完整 Python 158 passed；Compose 和 diff 检查通过。

仓库外 5 账号低频 canary 结果为 3 success、2 failed；失败分别是一次 HTTP 412 和一次 Provider `-352`，均未重试，风控不连续且断路未打开。该结果证明分类与停止边界生效，但不能证明批量覆盖、生产 SLA 或商业授权。

因此没有重新运行完整 20 关键词 Gate。原 `20260716-183040` 失败基线完整保留，Gate 结论仍为未通过，P0-D 仍被阻塞。详细记录见 [P0-C Creator Provider Recovery](content-intelligence-p0c-recovery-20260716.md)。

## 真实性边界

- 当前只支持 B 站公开搜索快照，不是全站穷举。
- 样本份额不是市场份额；第一次运行不能证明增长趋势。
- Development Search/Creator Provider 不代表生产商业授权或稳定 SLA。
- 没有真实用户效果、代表视频、ASR、确定性商业指标完整实现、`IntelligenceReport`、完整前端报告、部署或周期监控。
