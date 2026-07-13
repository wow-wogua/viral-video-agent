# 爆款视频分析

面向小规模公开测试的 B 站单平台内容分析产品：输入赛道、选题或竞品需求，生成带真实视频样本、来源链接、结构化结论和可执行建议的报告。

> 当前真实视频搜索仅支持 B 站。项目不会宣称支持抖音、快手或小红书实时分析。

## 产品截图

![产品首页](output/playwright/home-desktop.png)

<details>
<summary>移动端首页与用户 Dashboard</summary>

![移动端首页](output/playwright/home-mobile.png)

![用户 Dashboard](output/playwright/dashboard-desktop.png)
</details>

## 产品能力

- 注册、登录、退出与 HttpOnly Cookie 会话；密码使用 Argon2 哈希
- PostgreSQL 长期保存用户、任务、报告、Evidence、反馈、用量和分享链接
- Arq + Redis 执行 2–5 分钟后台分析任务，支持幂等、取消、有限重试、超时和轮询进度
- LangGraph v2 保持默认主链路：Entry → Planner → Research Loop → Evidence Gate → Analyst → Writer
- v1 Supervisor 回环保留为 A/B 与回退，不作为产品默认流程
- 每条 Evidence 获得稳定 `evidence_id`；Observation 必须引用真实 Evidence
- 报告数据附录由程序确定性生成，不完全交给 LLM
- 高熵只读分享链接支持过期与撤销；公开页不暴露用户、成本和内部执行轨迹
- Markdown 导出、浏览器打印/PDF、反馈与用量记录
- MiMo ASR 内容深度分析：独立 OpenAI 兼容客户端，讯飞保留为可选回退
- 桌面、平板、手机与深浅主题响应式界面

## 架构

```text
Next.js UI
  │ HttpOnly Cookie / polling
  ▼
FastAPI ─────────────── PostgreSQL 16
  │ create/enqueue        users/jobs/reports/evidence/feedback/usage/shares
  ▼
Arq + Redis
  │ queue/status/events/cache/locks
  ▼
Worker → LangGraph v2 → MCP tools → Bilibili / ChromaDB / optional ASR
```

Compose 包含 8 个服务：`frontend`、`app`、`worker`、`postgres`、`redis`、`chromadb`、`mcp-server`、`nginx`。PostgreSQL、Redis 和 ChromaDB 均使用 Docker 命名卷，不把数据库内部文件写入仓库。

详细说明：

- [产品架构与任务流](docs/product-mvp.md)
- [权限、数据与 Evidence 边界](docs/security-and-data.md)
- [2026-07-13 验收记录](docs/validation-20260713.md)

## 快速开始

```powershell
git clone https://github.com/wow-wogua/viral-video-agent.git
cd viral-video-agent
Copy-Item .env.example .env

# 编辑 .env：至少配置通用 LLM Key、POSTGRES_PASSWORD 和 JWT_SECRET
docker compose up -d --build

# 查看状态
docker compose ps
docker compose logs -f app worker
```

访问：

- 产品：<http://localhost:3000>
- API 文档：<http://localhost:8000/docs>
- 经 Nginx：<http://localhost>

数据库迁移由 `app` 启动命令自动执行，也可以手动运行：

```powershell
docker compose run --rm app alembic upgrade head
```

## 环境变量

生产环境必须更换：

```dotenv
APP_ENV=production
POSTGRES_PASSWORD=replace-with-a-strong-password
JWT_SECRET=replace-with-at-least-32-random-bytes
```

通用 MiMo LLM 继续使用 Anthropic 兼容接口：

```dotenv
ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=https://token-plan-cn.xiaomimimo.com/anthropic
LLM_MODEL_ID=mimo-v2.5-pro
```

MiMo ASR 使用独立 OpenAI 兼容接口：

```dotenv
MIMO_API_KEY=
MIMO_ASR_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_ASR_MODEL=mimo-v2.5-asr
MIMO_ASR_LANGUAGE=zh
TRANSCRIPT_PROVIDER=mimo
```

同一个 Key 可以复用，但两个协议客户端不能混用。没有配置 ASR 时，前端禁用内容深度分析；转写失败时 Worker 降级为元数据分析，不编造视频内容。

## 后台任务 API

```text
POST   /jobs
GET    /jobs
GET    /jobs/{job_id}
POST   /jobs/{job_id}/cancel
POST   /jobs/{job_id}/retry
GET    /jobs/{job_id}/events
GET    /reports/{report_id}
POST   /reports/{report_id}/shares
POST   /reports/{report_id}/feedback
```

状态：`pending`、`running`、`completed`、`partial`、`failed`、`cancelled`。

Redis 只保存队列、临时状态、事件和缓存；长期业务事实全部进入 PostgreSQL。

## Evidence 引用

Analyst 输出：

```json
{
  "claim": "代表样本的标题普遍明确指出任务和结果",
  "claim_type": "observation",
  "evidence_ids": ["ev_12345678abcdef00"],
  "confidence": 0.86
}
```

- `observation` 没有 Evidence 会被拒绝
- 不存在的 `evidence_id` 会触发 `REPORT_VALIDATION_FAILED`
- Writer 只能使用已有 claim 与 Evidence
- 程序追加结构化结论索引和数据附录
- 报告明确说明样本边界，不把单个视频外推为行业规律

## ASR 与音频边界

Worker 镜像内置 `ffmpeg` 和 `yt-dlp`。内容深度分析只处理公开可访问且用户有权分析的 B 站内容：

- 仅接受 B 站 HTTPS URL，不绕过登录、付费或访问控制
- 最长 600 秒，Base64 后最大 10MB
- 音频只在 `tmp/` 临时存在，任务后自动删除且禁止提交
- 按 BVID 与 `audio_hash` 缓存转写
- 自动测试全部使用 Mock，不调用真实收费 API

## 测试

```powershell
# Python
.\.venv\Scripts\python.exe -m pytest -q

# 前端
cd frontend
npm run lint
npm run build

# Compose
cd ..
docker compose config --quiet
```

当前验收：43 条 Python 测试，其中包含 20 条冻结 B 站产品输入回归；完整记录见 [验收文档](docs/validation-20260713.md)。

## 研究评测边界

- RAG：40 篇、235 个标题感知 chunk；自建固定集 28/28 命中，不代表开放域泛化
- v2 架构 A/B：两组历史任务中 LLM 调用由 16→7、14→6，耗时由 164.8s→79.4s、179.6s→119.4s
- 微调模型仅为 Researcher 可选 A/B 路径；direct-adapter hard/holdout 未证明稳定优于最强基座，因此产品默认仍使用 API 模型
- BFCL、tau-bench 均为风格化自建评测，不是官方榜单

## Logo 与品牌

`frontend/public/logo-mark.svg`、`logo-wordmark.svg`、`favicon.svg` 和 `frontend/src/components/Logo.tsx` 均为本项目原创代码原生 SVG。图形由播放三角、趋势线和 Evidence 节点组成，不使用 B 站电视图标、粉色品牌元素或第三方商标素材。
