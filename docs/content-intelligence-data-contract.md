# 内容竞争情报数据契约（P0）

当前版本：`content-intelligence.p0.1`

## 固定产品边界

- 单任务最多请求 5 页，最多输出 5 个重点竞品。
- 视频以 BVID 去重；创作者以 MID 去重。
- 每个竞品默认选择 6 条代表视频：3 条近期相关、2 条高播放、1 条高互动，重复时去重补位。
- ASR 只处理已选代表视频，每个竞品 1～3 条，并受全任务上限约束。
- 第一次运行只描述当前搜索快照，不计算增长率。
- 当前开发 Provider 不等于获得商业生产授权的数据源。

## 版本化对象

代码定义位于 `src/intelligence/contracts.py`：

- `SearchRequest`：关键词、排序、时间范围、分区、最大页数、分析模式、ASR 选项、过滤条件和幂等键。
- `CrawlRun`：Provider、逐页结果、覆盖数量、执行状态和截断原因。
- `SearchPage`：页码、请求时间、来源、状态、数量、原始响应 hash 和错误。
- `Video`：BVID、MID、标题、元数据、互动字段、观测时间、Provider 和缺失字段。
- `Creator`：MID、名称、主页、近期样本可用性和缺失原因。
- `CreatorSample` / `CreatorVideo`：独立 Creator Provider 的公开主页观测、最新最多20条投稿、30/90天窗口、来源和缺失状态；不与搜索候选页混写。
- `CreatorQualificationEvidence`：关键词范围内的账号主页、最新投稿审计、近 90 天样本与相关计数、粉丝、相关播放中位数和 Evidence；不得由单条搜索视频或仅历史集中投稿推导当前资格。
- `CompetitorScore`：分项、扣分、总分、置信度和入选/排除理由。
- `RepresentativeSelection`：选择类型、顺序、原因和 Evidence。
- `MetricResult`：固定指标枚举、公式版本、数值、分母、窗口、缺失和极端值规则。
- `IntelligenceReport`：查询、覆盖、竞品、指标、差异、风险、建议和 Evidence。

所有未知数值保留为 `null`，不得由 LLM 补齐。

## 成功状态

- 页面 `success`：请求成功且有规范化结果。
- 页面 `empty`：请求成功但没有结果；仍计入成功响应页。
- `failed/timeout/cancelled`：不计入成功响应页。
- 0 个成功响应页：任务失败或取消，不生成正常报告。
- 1～请求页数减 1 个成功响应页：任务为 `partial`，报告顶部必须显示部分成功；若仍无视频则报告为 `insufficient_data`，不得伪装成正常部分结论。
- 所有请求页均成功但全部为空：任务为 `empty`，报告为 `insufficient_data`，不生成正常竞争结论。
- 所有请求页均成功且存在视频：才允许标记正常成功。

## Evidence

- 搜索页保存来源 URL 或原始响应 SHA-256。
- 视频、竞品分数、代表视频和指标都携带来源 Evidence ID。
- 数值报告由程序从结构化对象渲染；LLM 只能解释已有数值。
- 0 页成功、未知 Evidence、缺失部分成功提示都属于发布门禁失败。

## 评测数据边界

- 仓库只保存 Schema、校验器和脱敏开发夹具。
- 完整 20 关键词、人工标签和隐藏 holdout 保存在仓库外。
- 未经真实复核的数据必须标记 `unreviewed` 或 `initial_labeled`，不得写成双人标注。
- 检索候选、人工参考候选、合格人工参考集和程序 Top 5 必须分开保存。
- 人工补充账号默认是 `discovery_only`；只有通过版本化账号资格政策后才成为 `qualified_reference` 或 retrieval miss。
- `discovery_only` 和 `emerging_candidate` 不进入 Retrieval Recall 分母，也不能伪装成系统召回或合格 Top 5。
- 检索池中的 `TopCreatorLabel` 同样保存账号资格状态和证据；`qualified_top5_count` 必须等于真实 `qualified_reference` 数量，不能用搜索片段上的 `keep` 数量代替。

## P0-B 实现

Search Provider、分页编排、Import Provider、规范化、去重、per-crawl-run 不可变 observation、数据库快照和 API/Worker 接入见 [P0-B Search Provider 与搜索快照](content-intelligence-search-providers.md)。全局 BVID/MID 实体保存最新归一化状态，历史 API 只读取目标 crawl run 的冻结视频/创作者观测。P0-B 成功只表示搜索快照完成；`actual_competitor_count` 仍为 0，不代表 Top 5、代表视频或情报报告已经实现。

## P0-C 实现

Creator Provider、逐视频相关性、资格政策、评分、Top 5、评测公式和独立查询接口见 [P0-C Creator Provider、竞品相关性与 Top 5](content-intelligence-competitor-scoring.md)。P0-C 只保存结构化账号审计和竞品结果，不创建正常报告，不进入代表视频、ASR、确定性商业指标或 `IntelligenceReport`。
