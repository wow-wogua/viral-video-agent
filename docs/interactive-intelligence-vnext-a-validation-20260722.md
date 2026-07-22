# vNext-A 验证记录（2026-07-22）

## 范围与 Git

- 仓库：仓库根目录
- 起始分支：`main`
- 起始 SHA：`a5fb6b14de0db02ce3fd2d10565cd798fd6e41b7`
- 工作分支：`feat/interactive-intelligence-vnext`
- 最终提交与远端状态：在 Gate Review 完成后记录于最终汇报。
- 未修改 `feat/content-intelligence-p0` 或 `archive/p0c-architecture-failed-20260719`。

## 功能验证边界

- `ENABLE_INTERACTIVE_BRIEF=false` 为默认值，App 与 Worker 配置一致。
- 自动化 Brief Validator 使用 Fake/Mock LLM；外部 LLM、UAPI、ASR、B 站和 MCP 调用均为 0。
- 没有真实收费 canary，外部费用为 0。
- Job 页包含极简回答表单；没有复杂对话 UI 或视觉重构。
- 没有候选账号确认；没有修改 P0-C 账号资格、评分、排序、权重或 Provider。
- 没有证明候选质量提升，没有重新打开 P0-C，没有进入 P0-D/P0-E。

## Migration 往返

- 使用独立临时 PostgreSQL 16 容器，不接触 Compose 正式卷；验证后容器已删除。
- `upgrade head` 后 current 为 `20260722_0002 (head)`，`alembic check` 无漂移。
- downgrade 到 `20260713_0001` 后，4 个新增列和 `job_clarifications` 表的残留计数为 `0 / 0`。
- re-upgrade 后，新增列和表的恢复计数为 `4 / 1`；current 再次为 `20260722_0002 (head)`，`alembic check` 无漂移。

## 自动化与静态检查

- `tests/test_interactive_brief.py`：10 passed。
- `tests/test_product_api.py tests/test_graph_v2.py tests/test_model_bootstrap.py`：22 passed；与新增定向测试合计 32 passed。
- 完整 Python pytest：72 passed，只有既有 LangGraph pending-deprecation warning。
- Python compile、`docker compose config --quiet`、前端 lint、TypeScript、生产 build 和 `git diff --check` 均通过。
- Playwright 验证：1440px、375px、812×375 横屏、浅色/深色、reduced-motion 均无横向溢出；模板登录回跳保留参数并正确预填；澄清回答提交后由 `waiting_user` 恢复为 `pending`；控制台 0 error / 0 warning。
- 最终首页截图：`output/playwright/vnext-a-home-final-20260722.png`。

## Gate 结论

vNext-A 工程 Gate 通过。该结论只覆盖默认关闭的 durable clarification backend、极简回答闭环和兼容性回归，不代表候选质量提升或完整竞争情报产品完成；本任务停在 Gate Review，不自行进入 vNext-B。
