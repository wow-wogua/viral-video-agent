# P0-C 分层架构失败实验与冻结说明

状态：`architecture_candidate_invalid_stop`；`candidate_valid=false`；`entered_p0d=false`。

## 实验边界

P0-C v3 新盲评失败后，总控只额外授权了一次真正分层的架构 development 实验，用于判断“逐视频分类 → 账号画像 → 确定性资格 → 独立排序”是否能产生通用改善。本轮不是继续调参，也不授权进入 P0-D。

实验只使用此前已审核关系组成的 97 项 development set。它没有生成第二轮 holdout，不代表最终线上质量，也没有改变既有评测关键词、人工标签或 Gate 定义。

## 脱敏结果

| 指标 | 历史 v3（同一 development set） | 分层架构候选 |
|---|---:|---:|
| relevance exact | 55.67% | 71.13% |
| specialization exact | 57.73% | 55.67% |
| role exact | 30.93% | 43.30% |
| qualification exact | 48.45% | 43.30% |
| selected precision | 76.19% | 69.23% |
| strict Precision@5 | 88.89% | 50.00% |
| irrelevant false-positive rate | 4.76% | 7.69% |
| output coverage | 100.00% | 66.67% |
| selected count | 21 | 13 |
| abstention keywords | 11/20 | 14/20 |

relevance 和 role 有局部改善，但 specialization、qualification、selected precision、strict Precision@5 和 output coverage 退化；输出减少且 abstention 增加。该结果不能解释为通用架构成功，也不能通过少输出来包装为质量达标。

## 冻结与归档

- 没有 architecture freeze，没有把失败候选采用为运行时代码。
- 本次收口不重新运行 LLM 评测，不修改算法、Prompt、资格、排序或 Gate。
- 失败源码、测试和脱敏文档只保存在本地分支 `archive/p0c-architecture-failed-20260719` 与仓库外 Git Bundle，未推送 GitHub。
- 私有逐项结果、缓存和评测数据继续只保存在仓库外；Git 文档不包含真实关键词、MID、账号名、标题或完整模型响应。
- P0-C 正式冻结；P0-D、P0-E 均未开始。

P0 整体因 P0-C 质量 Gate 失败而终止，不是已经完成。该阶段不承诺 Top 5 质量已达标、全站覆盖、市场份额、趋势或生产 SLA。
