# 内容竞争情报评测方法（P0）

评测契约版本：`content-intelligence-eval.p0.3`

账号资格政策版本：`creator-qualification.p0.1`

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
