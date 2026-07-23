# vNext-B 验证记录（2026-07-23）

## Gate 范围与 Git

- 仓库：仓库根目录
- 基线分支：`feat/interactive-intelligence-vnext`
- 起始 SHA：`c34214e0570a7a8b3258fc9be6e0c6cbff0b10a3`
- 工作分支：`feat/interactive-intelligence-vnext-b`
- 未合并 `main`，未修改 `feat/content-intelligence-p0` 或 `archive/p0c-architecture-failed-20260719`。
- 最终提交、远端 SHA、ahead/behind 和工作树状态以本次 Gate 汇报为准。

## vNext-B 设计结论

### 澄清历史

`GET /jobs/{job_id}/clarification` 先校验 Job 所有权，再分开返回：

- `current`：只包含 `waiting_user` 当前可回答的问题。
- `history`：只包含按 round 升序排列的已回答记录，包括所选选项、自定义回答、状态和回答时间。

接口不返回内部 Prompt、模型原始响应、Key、Cookie 或其他敏感执行数据。Job 页也把当前问题与历史回答分成独立区域。

### 范围修订

采用“根据旧任务创建新 Job”，不原地修改旧 Job。新 Job 通过 `revision_of_job_id` 指向来源；旧、新 Job 都记录审计事件。旧 clarification、TopicSpec、报告和用量保持原记录。

- `pending`、`running` 拒绝修订。
- `waiting_user` 在同一事务内先取消旧任务，再创建修订任务；旧问题和回答不删除。
- `failed`、`cancelled`、`completed`、`partial` 可作为不可变来源。
- 来源 Job 已有修订时禁止删除，避免破坏审计链。
- 新 Job 从 `clarification_round=0`、`execution_version=0`、`retry_count=0` 开始。

没有选择重置同一 Job，因为它会混淆轮次、执行版本、报告归属和历史审计。

### Commit / enqueue 崩溃窗口

采用 PostgreSQL reconciliation，不引入完整 transactional outbox。理由是当前只需恢复一种可由 Job 状态完整重建、且已有确定性 ID 的 Arq 消息；新增 outbox 表和发布生命周期会扩大当前阶段的迁移与运维面。

- 创建、回答、retry 和修订在提交 `pending` 时写入 `dispatch_pending_at`。
- Worker 每分钟运行一次有限批量扫描；默认只处理超过 60 秒、`pending + arq_job_id=null` 的记录。
- 恢复复用原 `execution_version` 和 `analysis:{job_id}:v{execution_version}`，不增加 `retry_count`。
- cancelled、failed、running、waiting_user、completed、partial、近期任务或已有 Arq ID 的任务不会被恢复。
- 恢复前、成功和失败都有审计事件；失败后至少再等待安全阈值，不忙等待。
- Redis 已接收但数据库未保存 Arq ID 时，重复派发仍使用同一个队列身份。

Migration `20260723_0003_interactive_vnext_b.py` 增加 `revision_of_job_id`、`dispatch_pending_at`、外键和扫描索引。

## 自动化验证

- vNext-B 定向：`12 passed`，其中包含 API 提交后、enqueue 前模拟进程退出并恢复。
- `tests/test_interactive_brief.py`：`14 passed`，vNext-A 回归保持通过。
- `tests/test_product_api.py tests/test_graph_v2.py tests/test_model_bootstrap.py`：`22 passed`。
- 完整 Python pytest：`88 passed`；只有既有 LangGraph pending-deprecation warning。
- Python compile、`docker compose config --quiet`、前端 lint、TypeScript/生产 build、`git diff --check` 均通过。
- 全部测试使用 Fake/Mock；没有调用真实 LLM、UAPI、ASR、B站或 MCP。

定向覆盖所有权隔离、current/history 顺序、旧回答不可变、新 Job 审计关系、非法状态、commit 后中断恢复、retry_count 不变、确定性 Arq ID、状态白名单、旧执行版本隔离、重复 reconciliation 幂等和默认关闭回退。

## Migration 往返

使用独立临时 PostgreSQL 16 容器，不接触项目正式卷：

- upgrade 到 `20260723_0003` 成功。
- downgrade 到 `20260722_0002` 后，新列/索引残留为 `0 / 0`。
- re-upgrade 后，新列/索引恢复为 `2 / 2`。
- `alembic check` 无漂移。
- 临时容器已删除，Docker Desktop 恢复为停止状态。

## 浏览器与可访问性 QA

真实 Chromium 验证了澄清历史、当前问题分区、修订表单、报告页入口、修订后导航和来源链接：

- 桌面浅色：`output/playwright/vnext-b-clarification-history-desktop-20260723.png`
- 375×812 移动端浅色：`output/playwright/vnext-b-revision-mobile-20260723.png`
- 375×812 移动端深色：`output/playwright/vnext-b-revision-mobile-dark-20260723.png`

修订表单支持 Tab/Enter 键盘操作；按钮 loading/disabled 明确；Textarea 有真实 label；澄清选择保留 fieldset/legend；错误使用 `role=alert`。移动端 `scrollWidth/innerWidth=375/375`，无横向溢出；浏览器控制台 0 error / 0 warning。开发服务器仍会输出既有 Next 本地跨域 future warning 和 Node deprecation warning，不影响生产 build。

## 安全、外部调用与边界

- 未读取或提交 `.env`；未硬编码 Key、Token、Cookie、账号、MID 或私有路径。
- 未提交 QA SQLite、Playwright 调试快照、缓存、构建目录、真实响应或大型调试文件。
- 外部业务调用 0，费用 0。
- PostgreSQL 业务状态机仍不等于 LangGraph 原生 interrupt/resume。
- 本阶段没有证明候选账号选择质量提升。
- P0-C 继续失败冻结；P0-D/P0-E 未开始。
- vNext-C 候选账号人工确认尚未开始。

## Gate 结论

vNext-B 为 Gate 候选，等待总控复核。该结论只覆盖澄清历史、可审计范围修订、派发崩溃窗口恢复、必要前端入口和兼容性回归；不得据此自动进入 vNext-C。
