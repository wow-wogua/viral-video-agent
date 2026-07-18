# P0-C v3：账号主题资格校准与新盲评协议

当前候选版本：`creator-topic-assessment.p0.2` / `creator-qualification.p0.2` / `competitor-selection.p0.3` / `competitor-evaluation.p0.2`

## 阶段边界

P0-C v3 只修复账号—主题预测、资格门禁、核心账号排序和独立评测语义。它不进入 P0-D，不新增 Creator/UAPI/B站/网络请求，不新增 LLM 调用，不调整冻结关键词，不生成代表视频、ASR、商业指标或完整情报报告，也不新增 migration。

53 项人工审核只作为 development/error-analysis set。新盲评从未进入这 53 项的账号—关键词关系中生成；代码、规则和选择结果先提交冻结，盲评标签只能用于 `competitor-evaluation.p0.2` truth mapping 和 Gate 指标。

## 只读误差分析

旧无偏 Gate 的 20.69% 是 frozen `qualified_reference` 命中 6 / 系统输出 29，不等于账号主题相关性只有 20.69%。29 个输出中有 22 个此前没有 frozen qualified/excluded 状态，因此 unresolved selection rate 为 75.86%。

53 项三维审核的系统/人工 exact match：

- relevance：29 / 53，54.72%。系统 relevant 中人工为 relevant 29、uncertain 5、irrelevant 2；系统 uncertain 中人工为 relevant 16、irrelevant 1。
- specialization：29 / 53，54.72%。主要误差是系统 low 但人工 high/medium，以及少量系统 high 但人工 medium/low。
- role：9 / 53，16.98%。旧系统主要只有 specialist/generalist 两种预测，不能表达 educator、reviewer、service 等业务角色。

pre-HITL 选中且完成三维审核的 22 项中：

- 人工 relevance：17 relevant、4 uncertain、1 irrelevant。
- 人工 specialization：20 high、1 medium、1 low。
- 人工 role：13 educator、5 reviewer、2 specialist、1 service、1 aggregator。

按独立 development truth mapping，22 项分为 14 core、1 adjacent、1 occasional、2 excluded、4 insufficient。系统判为 core 的 23 个已审关系，其第一失败层为：relevance 5、role 2、qualification 1；15 个关系的 core 判断成立。排序层只有 1 个关键词存在“已审错误选中与已审正确未选中”可直接换位，说明主要问题在排序之前。

风险计数（全部 53 / pre-HITL 已审选中 22）：

- single-video bias：5 / 0。
- generalist 误判：16 / 0。
- aggregator/reupload：2 / 1。
- service：3 / 1。
- relevant 但专业度不足：12 / 0。
- 旧政策相关比例不足：13 / 0。
- 90 天持续性不足：13 / 0；30 天持续性不足：12 / 2。
- 影响力不足：11 / 0。
- semantic-rule conflict：10 / 0。
- missing evidence：3 / 0。

类别已审样本为 broad 16、vertical 26、brand 6、ambiguous 3、low_result 2。旧选中中的非 core 主要集中在 vertical；brand 的唯一已审选中为 adjacent。该样本是路由后的开发集，不代表各类别自然分布。

完整逐项记录、真实账号、MID、关键词、投稿标题、人工理由和私有映射只保存在仓库外新 round，未进入 Git。

## v3 冻结设计

### A. System Prediction

`CreatorTopicPredictionV3` 保存 relevance、specialization、role、boundary risks、model confidence 和 system confidence。它复用冻结的逐视频语义标签，不重新调用 LLM；新增的角色信号只使用跨关键词通用的账号名/投稿文本边界词，不读取关键词、MID或人工标签。

任何聚合/搬运通用信号都会触发 `aggregation_or_reupload`，用于 core abstain；service、30 天持续性不足和低语义置信度也成为显式风险。角色信号是保守边界，不作为分数奖励。

### B. Qualification Policy

`creator-qualification.p0.2` 只决定产品关系，不排序：

- `core_competitor`：系统 relevance 为 relevant、specialization 为 high、角色可进入 core；model confidence 至少 0.85；至少 10 个已决投稿、5 个相关投稿、相关比例至少 60%；90 天至少 3 个且 30 天至少 1 个相关投稿；影响力通过；无聚合、missing evidence 或 semantic conflict。
- `adjacent_benchmark`：相关但 specialization 非 high，或 generalist/service，或相关比例不足 60%。
- `occasional_hit`：相关投稿不足或 30/90 天持续性不足。
- `excluded`：系统明确 irrelevant，或命中聚合/搬运硬边界。
- `insufficient_evidence`：低结果词尚无独立政策，或语义置信度、样本、Evidence、影响力不足。

不足 5 个 core 时不补位。所有 check 和 reason 结构化保存。

### C. Ranking

`competitor-selection.p0.3` 只对 `core_competitor` 排序：v1 base score 降序 → v2 system confidence 降序 → 搜索相关数降序 → 90 天相关数降序 → 最佳搜索位置升序 → MID 字符序。人工标签、人工角色、人工 truth、当前开发集覆盖状态不进入排序。

### D. Evaluation Truth

`competitor-evaluation.p0.2` 只读取人工 relevance / specialization / role 和独立客观 Evidence：已决样本、相关数量/比例、30/90 天持续性、粉丝/播放影响力与关键词类别。

truth mapping 不读取系统 prediction、system/model confidence、base score、qualification、selected 或 selection rank。评测 core 的相关比例门槛为 50%，低于系统 core 的 60%，避免用系统自身门槛循环证明系统正确。

## 一次开发集校准

本轮只冻结一次候选，没有 v4/v5 循环或权重搜索。使用同一 `competitor-evaluation.p0.2` truth mapping 对 v2 与 v3 复核：

- v2：29 个输出；22 个有开发标签；已审 precision 63.64%；14 个已审 core、8 个已审 non-core、7 个未覆盖。
- v3：21 个输出；14 个有开发标签；已审 precision 85.71%；strict reviewed-core-slot precision 80.00%；12 个已审 core、2 个已审 non-core、7 个未覆盖。
- 选择变化：移除 9、增加 1、保留 20；保留旧选中正确 core 的 85.71%，已知 non-core 减少 6，已知 core 减少 2。

这不是最终 Gate。改进包含更严格 abstention，且仍有 7 个全量池选中位置未被开发集覆盖；通用角色信号稀疏，高置信度的相邻主题误判仍可能与真阳性结构相似。只有新盲评可以判断是否泛化。

## 新盲评协议

代码提交冻结后，从全量冻结关系中先排除 53 项 development set，再运行同一 v3 资格和排序。盲评包必须：

- 覆盖该 unseen pool 中全部 v3 选中关系。
- 对有 v3 输出的关键词补充高分未选关系，使每个相关关键词最多形成 5 项审核池。
- 对无输出关键词加入少量高分未选关系，并覆盖 broad、vertical、brand、ambiguous、low_result。
- 总量 40–80；超过 80 直接停止。
- 工作簿只显示中立账号信息、冻结意图和投稿 Evidence，隐藏系统标签、分数、资格、选择状态、旧人工标签和 Gate 指标。

人工只填写 `human_relevance`、`human_specialization`、`human_role`、`human_reason` 和 `review_complete`。完成后严格导入全集、重复、枚举、reason、完成状态和 identity；选择器不得重跑。

最终 Gate 同时要求 selected precision ≥80%、strict Precision@5 ≥80%、irrelevant false-positive rate ≤10%、来源可追溯、规则和分数可解释。false-negative 只在盲评抽样池内报告，不包装为完整 Retrieval Recall。

## AI HOT 借鉴边界

2026-07-18 只核验其官方 [about](https://aihot.virxact.com/about)、[Agent 接入](https://aihot.virxact.com/agent) 和 [Skill 说明](https://aihot.virxact.com/aihot-skill/SKILL.md)。本项目只借鉴 candidate pool / selected 分层、先聚合去重降噪再精选、结构化意图、保留来源/时间窗/不确定性，以及 Agent 理解编排配合确定性 API/Gate 的设计思想。

没有安装 AI HOT Skill，没有调用其资讯 API/RSS，没有接入其 AI 新闻数据，没有复制后端代码，也没有因此重构 Next.js、FastAPI、LangGraph、P0-A 或 P0-B。

## 不变结论

无论新 holdout 结果如何，都停止在 P0-C Gate Review。通过只能写“P0-C v3 Gate候选通过，等待总控审核”；失败则冻结 P0-C，不继续 v4 或调参。P0-D 始终不允许进入。
