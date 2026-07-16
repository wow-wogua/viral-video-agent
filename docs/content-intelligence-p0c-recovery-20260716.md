# P0-C Creator Provider Recovery（2026-07-16）

## 结论

P0-C Recovery 工程修复完成，但完整 20 关键词 Gate **未重跑**。P0-C 仍停在 Gate Review，不能进入 P0-D。

旧失败基线 `20260716-183040` 保持只读且未覆盖。Recovery 只修复 Creator Provider 的通用可靠性和审计缺陷，没有修改 `competitor-score.p0.1`、`creator-qualification.p0.1`、`competitor-evaluation.p0.1`、冻结关键词或人工标签。

## 根因复核

请求链为：WBI nav（缓存 10 分钟）→ 每账号签名投稿请求 → 投稿成功后再请求粉丝公开统计。旧唯一 MID 进度文件包含 394 个账号：29 success、365 failed；唯一账号失败原因是 HTTP 412 共 304 个、Provider `-352` 共 61 个。关键词级复用后的既有验证汇总仍为 308/63。旧序列最长连续风控为 202 个，但实现没有停止，继续把剩余账号全部请求完。

复核没有发现能解释全部结果的确定性 WBI 签名错误：同一签名实现既取得成功，也在后续返回明确风控码。可确认的外部阻塞是公开接口风控和无稳定 SLA；可修复的工程缺陷是没有独立风控分类、连续计数、断路、有限重试审计和逐条原子进度。

## Recovery 实现

Development Creator Provider 版本升级为 `bilibili-public-creator.p0-c.2`：

- HTTP 412、Provider `-352/-412/-401/-403` 独立标记为 `risk_control`，默认不重试。
- 连续 3 个账号最终命中风控后打开固定断路器；记录 15 分钟 cooldown 信息，但当前进程不会长等待或自动恢复。
- 触发断路的账号保留实际失败；后续账号不发网络请求，保存为 `missing + not_attempted_due_to_risk_control`。
- 只有超时、连接错误、429 和 5xx 最多重试 2 次；退避为 0.5 秒、1 秒。
- 每次请求保存 operation、attempt、HTTP/Provider 分类、限频等待、退避和最终 circuit 状态；不保存响应正文、Cookie 或完整查询参数。
- 默认客户端不读取个人 Cookie，并设置 `trust_env=False`，不使用环境代理进行风控规避。

私有采集进度升级为 `creator-capture-progress.p0-c.2`：

- 每个账号完成后原子 checkpoint，不再每 5 个才保存。
- 同一 round 恢复会校验 Provider 版本、目标集合哈希和数量，并跳过已有成功或失败观测。
- 已打开断路的 round 恢复时不再发网络请求。
- 新 round 必须使用新的空目录和 `capture_round_id`；旧失败目录不能作为新 round 覆盖目标。
- `--capture-only` 和全局账号上限用于小规模 canary；若完整采集触发断路，脚本写 `gate-not-run-summary.json` 并停止，不进入 LLM 或 Gate。

Import Creator Provider 版本升级为 `import-creator.p0-c.2`，保持 `creator-import.p0.1` 载荷兼容，并增加可选的 `source_basis`、`authorization_status`、`capture_round_id`、目标数量和目标集合 SHA-256。程序可验证 expected/imported 的 exact coverage；公开无认证采集只能声明 `development_only`，用户导出需要用户确认，供应商导出需要书面授权。字段声明不能替代合同或商业授权本身。

## 自动化验证

命令均设置 `PYTHONDONTWRITEBYTECODE=1`，pytest 使用 `-p no:cacheprovider`。

- P0-C/Recovery 定向：41 passed。
- P0-B 回归：42 passed。
- P0-A 回归：36 passed。
- 完整 Python：158 passed，1 条既有 LangGraph PendingDeprecationWarning。
- `docker compose config --quiet`：通过。
- `git diff --check`：通过。

测试覆盖 transient retry/backoff、412、`-352`、连续计数重置、固定断路、断路后零请求、逐条 checkpoint、同 round 幂等恢复、新 round 隔离、Import 来源和 exact coverage。

## 真实 canary

在仓库外新 round `20260716-200338-recovery-canary` 执行 5 个账号、3 秒最小请求间隔、capture-only、无 Cookie、无环境代理的单次公开 canary：

- 5/5 实际尝试；3 success、2 failed、0 not_attempted。
- 两个失败分别为一次 HTTP 412 和一次 Provider `-352`；均 0 retry。
- 共 9 次 HTTP attempt；7 success、2 risk_control。
- 风控不连续，最终 consecutive=0，断路保持 closed。
- 没有运行 LLM，没有生成 Top 5，也没有重新搜索 P0-B 的 20×5 页。

该 canary 只验证错误分类、有限请求和审计语义。3/5 可用样本不能证明批量覆盖、生产 SLA 或商业授权；两种风控仍在最小样本中出现。

## 完整 Gate 与数据来源

完整 20 关键词 Gate 未重跑，原因是当前 Development Provider 在 5 个低频样本中仍只有 60% 可用，且没有生产商业授权或稳定覆盖证据。现有可继续接入的合法路径只有：

- 用户提供并确认有权使用的账号投稿导出；
- 有书面授权和缓存/衍生报告权利的供应商导出；
- 合作 UP 主或客户授权数据。

当前没有上述正式数据。不能用人工正例、个人 Cookie、登录、验证码绕过、代理池或调整评分规则补过 Gate。若总控不提供合法中立的完整账号数据，应暂停 P0；即使未来重新评测通过，也只能停在 P0-C Gate Review，不能自动进入 P0-D。

当前人工基线仍只有 1 名真实复核者，没有双人标注或一致性证据。
