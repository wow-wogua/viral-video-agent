# 内容竞争情报评测方法（P0）

评测契约版本：`content-intelligence-eval.p0.3`

冻结账号资格政策版本：`creator-qualification.p0.1`；历史 v3 评测版本：`creator-qualification.p0.2`

## 为什么拆成三层

旧式“看搜索第一页后直接写 Top 5”会混淆三个问题：搜索是否召回、账号是否真正相关、评分器是否选对。P0 将其拆开：

1. **检索候选池**：只保存精确 SearchRequest 在最多5页内实际返回的账号，不允许人工补写。
2. **人工参考候选**：人工可以通过定向公开搜索或已有领域知识补充候选，但发现时默认只是 `discovery_only`，不能直接进入人工相关参考集。
3. **程序 Top 5**：只能从检索候选池产生，不能把人工补充账号伪装成系统召回。

因此：

- Precision@5 衡量程序从候选池选出的账号是否相关。
- Retrieval Recall 只以 `qualified_reference` 为分母；`discovery_only` 和 `emerging_candidate` 不进入分母。
- 人工补充但未召回的账号记为 retrieval miss，用于改进通用检索策略，不直接提高 Top 5 分数。
- 检索候选的 `keep/exclude/uncertain` 只是人工判断；`keep` 只有附带相同账号级资格证据并升级为 `qualified_reference` 后才计入 `qualified_top5_count`。

## 账号资格与搜索视频相关性

搜索结果标题或某条视频相关，只能生成视频级 `RelevanceDecision` 或发现账号，不能证明账号具备竞品资格。账号资格必须基于账号主页及公开投稿样本单独审计。

状态含义：

- `discovery_only`：由相关性搜索、最多播放搜索或人工知识发现，但尚未完成账号级审计。
- `emerging_candidate`：持续相关性通过，但粉丝和相关视频播放影响力门槛均未通过；不进入 Retrieval Recall 或 Top 5。
- `qualified_reference`：持续相关性和影响力都通过，才可进入人工相关参考集和 Retrieval Recall 分母。
- `excluded`：账号级审计确认不相关或不符合冻结业务意图。

`creator-qualification.p0.1` 冻结规则：

- 审计账号最新最多 20 条公开投稿，并记录其中近 90 天投稿和相关投稿数量。
- 最新最多 20 条中至少 3 条相关视频，且近 90 天内至少 3 条相关视频；`uncertain` 不进入相关占比分母。
- 仅历史上集中发布过相关内容、近 90 天已经不活跃的账号可以保留为历史发现证据，但不进入当前 Retrieval Recall 或 Top 5。
- 宽泛词或综合创作者的相关内容占比至少 20%。
- 垂类及其他非宽泛、非综合创作者的相关内容占比至少 30%。
- 影响力满足 `粉丝数 >= 10000` 或 `相关视频播放中位数 >= 5000` 中任一项。
- 低结果词不自动套用或降低上述门槛，必须使用另一个明确版本化的资格政策。
- `qualified_reference` 必须保存账号主页、观测时间、样本计数、粉丝数/播放中位数以及至少 3 个账号样本 Evidence URL。

人工状态必须与真实人数一致：`unreviewed` 和 `initial_labeled` 的 `reviewer_count=0`；`user_reviewed` 至少有 1 名真实人工；只有 2 名真实人工完成裁决时才可写 `adjudicated`。当前文件不得把模型初排、聊天协助或程序校验计作第二名人工。

为兼容已有私有文件，旧 `top_creators` 和 `expected_relevant_creators` 字段继续读取，但缺少资格字段的条目一律默认为 `discovery_only`。旧的 `keep` 不自动变成合格 Top 5。

## 混合内容账号

账号有其他内容不等于不相关。人工标注同时记录：

- `role`：垂类创作者、综合创作者、官方账号、媒体、教育、经销/服务、聚合搬运或内容农场。
- `focus_level`：high、medium、low 或 unknown。
- `decision`：keep、exclude 或 uncertain。

综合创作者可以保留，但必须通过账号级 20% 相关占比和其他资格门槛。只有单条命中或拿不到近期样本时，保持 `discovery_only` 或标记 uncertain，不作为人工 Top 5 正例。

## 分类规则

- **宽泛词**：先冻结业务意图和允许子主题；综合媒体不能仅凭一条新闻进入 Top 5。
- **垂类词**：重视近期持续相关性；课程矩阵、搬运和重复上传单独标记。
- **品牌词**：区分官方、测评媒体、行业分析、用户内容和经销服务；是否相关由报告用途决定。
- **歧义词**：必须写明目标含义，例如“苹果=Apple科技品牌”“Java=编程语言”。
- **低结果词**：允许少于5个合格账号，禁止用弱相关账号补满。

## 防止评测污染

- 完整关键词、人工参考集和隐藏 holdout 只保存在仓库外。
- 业务代码不得包含评测账号、MID或关键词特判。
- 定向人工搜索只用于建立参考集，不改变原始 SearchRequest 的候选快照。

## P0-C 冻结统计

`competitor-evaluation.p0.1` 同时报告 selected precision、strict Precision@5、不相关账号误判率、unresolved selection rate、输出覆盖、Retrieval Recall、类别统计和 abstention。少于5个输出时，strict Precision@5 的分母为 `min(5, 当前检索池中 qualified_reference 数)`，空槽位不能被隐藏；没有 qualified 槽位时该指标为 null，并保留 0 输出事实。完整公式见 [P0-C Creator Provider、竞品相关性与 Top 5](content-intelligence-competitor-scoring.md)。

当前私有文件为 1 名真实人工复核，`reviewer_count=1`，没有标注者一致性证据。模型、程序校验或聊天协助不得计作第二名人工。

## P0-C v2 方案C人工审核

方案C不继续旧 400 项逐视频全量审核，而是审核有限的“关键词—账号”单元，并把三个维度独立填写：

- `human_relevance`：relevant / irrelevant / uncertain。
- `human_specialization`：high / medium / low / unknown。
- `human_role`：跨赛道通用账号角色。

Gate 盲评工作簿隐藏 LLM 建议、系统分数、v1/v2 选择状态、qualification、产品关系、Gate 指标和原人工标签。Review Router 优先覆盖 v2 未标注选中、v1 unresolved 选中、v1/v2 冲突、规则/语义冲突和每关键词最多 1 个非选中抽样，并复用已有 frozen qualified/excluded 标签。

人工导入必须严格校验 review_id 唯一性与全集覆盖、枚举、reason、完成状态和不合法组合；不得静默修正输入。v2 Gate 完成后继续以冻结 qualified reference set 计算 Retrieval Recall，非选中分层抽样只作为 sampled false-negative audit。完整规则见 [P0-C v2 方案C](content-intelligence-p0c-scheme-c.md)。

2026-07-18 的 53 项审核已严格导入，完成 53/53、冲突数 0，实际 `reviewer_count=1`。这证明 HITL 审核、导入、关系 overlay 和产品辅助选择链路可运行，但人工标签不得进入无偏质量 Gate 的资格、排序或 Top 5；冻结 `qualified_reference` / `excluded` 只能在系统结果固定后用于计算指标。

完整性复核纠正了原判定：旧流程同时用 frozen qualified 改写 `product_relation`、通过 `preferred_mids` 改变 Top 5，又用同一标签计算 Precision，且只检查 strict Precision@5，因而 `with_reservation` 无效。纠正后的无偏 Gate 精确复现审核前系统输出，selected precision 20.69%、strict Precision@5 28.57%、不相关误判率 3.45%、unresolved selection rate 75.86%、输出覆盖 76.19%，状态为 `failed`。单独命名的 HITL 辅助输出为 42 个位置，诊断 selected precision 50.00%、strict Precision@5 100.00%、不相关误判率 0.00%，但它明确不是无偏质量 Gate。P0-D 继续阻塞。

## P0-C v3 独立 truth mapping、失败盲评与最终冻结

`competitor-evaluation.p0.2` 把人工 truth 映射与系统 prediction、qualification 和 ranking 完全隔离。它只读取完整人工 `human_relevance` / `human_specialization` / `human_role`，以及独立客观 Evidence：已决投稿数、相关投稿数与比例、30/90 天持续性、粉丝/相关播放影响力和关键词类别。

truth mapping 禁止读取 system/model confidence、系统 relevance/specialization/role、boundary risks、base score、qualification、selected 或 selection rank。人工 relevant + high specialization + core-eligible role 仍需至少 10 个已决投稿、5 个相关投稿、相关比例 ≥50%、90 天至少 3 个且 30 天至少 1 个相关投稿，并通过影响力；评测 core 的 50% 比例门槛故意低于系统资格的 60%，避免循环评测。

53 项只用于 development/error analysis，并对 v2/v3 使用同一 p0.2 truth mapping。新盲评先排除这 53 项关系，再由冻结 v3 代码在 unseen pool 中生成；工作簿隐藏系统标签、分数、资格、选择状态、旧人工标签和 Gate 指标。最终 Gate 不重新运行选择器，只读取冻结 selected positions 和完成的盲评 truth；false-negative 只在抽样未选关系中报告，不包装为完整 Retrieval Recall。

该新盲评已经完成：selected precision 为 57.14%、strict Precision@5 为 80.00%、不相关误判率为 14.29%，14/20 关键词零输出。selected precision 和不相关误判率未达到 Gate，输出覆盖也不足，因此 v3 状态为 `failed`。

总控随后额外授权一次真正分层的架构实验。它只在合并后的 97 项 development set 上运行，没有生成第二轮 holdout：relevance exact 为 71.13%、specialization exact 为 55.67%、role exact 为 43.30%、qualification exact 为 43.30%；selected precision 69.23%、strict Precision@5 50.00%、不相关误判率 7.69%、output coverage 66.67%，selected count 为 13，14/20 关键词 abstain。relevance 和 role 的局部改善不能抵消 specialization、qualification、严格槽位精度和 coverage 的退化；这些 development 数值不是新 holdout 或最终线上指标。

架构候选未冻结、未采用为运行时代码，也未推送 GitHub；失败源码只保存在本地归档分支和仓库外 Bundle。P0-C 正式冻结，P0-D、P0-E 均未开始。完整记录见 [P0-C v3](content-intelligence-p0c-v3.md)和[分层架构失败实验说明](content-intelligence-p0c-architecture-repair.md)。
