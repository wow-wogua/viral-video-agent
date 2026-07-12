# 爆款视频分析多智能体系统

基于 LangGraph 的短视频分析 Agent 系统，自动收集可用证据、分析爆款内容并生成策略报告。当前默认使用 v2 确定性主流程，保留 v1 Supervisor 回环用于 A/B 和回退。

## 架构

```text
v2（默认）: 用户输入 → 确定性入口 → Planner → Research Loop → Evidence Gate → Analyst → Writer
v1（回退）: 用户输入 → Supervisor → Planner/Researcher/Analyst/Writer → Supervisor → 报告
```

**核心设计：**
- v2 用规则完成意图与平台能力预检，正常流转不再让 Supervisor 每步调用 LLM；v1 仍可通过 `GRAPH_VERSION=v1` 启用
- 动态能力注册只暴露当前真实可用的工具/平台；抖音、快手、小红书实时搜索未接入时直接返回 `unsupported_platform`
- Researcher 在可用工具与 `none` 间选择，通过 MCP 调用并保留直接函数兜底；Pydantic 统一参数校验，搜索结果去重且单次最多 20 条
- 结构化工具结果记录 `success/empty/unavailable/error`，Evidence Gate 在无真实证据时返回 `partial`，不继续生成正常报告
- v2 Analyst 最多 2 轮、Writer 生成 1 次；v1 保留原自评与修订回环用于对照
- 请求携带稳定 `user_id`，长期记忆与 Redis 历史列表按用户隔离；Redis 只保存缓存、历史记录和 running/completed/partial/failed 状态，当前未接入 Celery
- CostTracker / TraceTracker / FallbackCounter 使用请求上下文隔离，避免并发请求串统计
- RAG 使用标题感知切分、稳定 chunk ID、文档/片段去重、向量候选 + 中文词项混合排序；返回章节、来源 URL 和来源等级
- `get_trend_data` 默认在真实数据源未配置时返回 `unavailable`；随机 mock 只在 `ENABLE_MOCK_TOOLS=true` 的显式演示模式启用

## 演示

### 首页
![首页](pictures/home.png)

### 分析中
![分析中](pictures/analysing.png)

### 报告页面
![报告页面](pictures/report.png)

### 历史记录
![历史记录](pictures/history.png)

### 执行轨迹
![执行轨迹1](pictures/trace1.png)
![执行轨迹2](pictures/trace2.png)

## 技术栈

| 组件 | 技术 |
|------|------|
| 编排框架 | LangGraph |
| LLM | MiMo / DeepSeek / 微调模型（Qwen3-4B LoRA） |
| 工具协议 | MCP (SSE) |
| 向量数据库 | ChromaDB |
| 后端 | FastAPI |
| 前端 | Next.js + Tailwind + Zustand |
| 缓存与状态 | Redis（缓存 / 历史记录 / 状态查询；无 Celery worker） |
| 反向代理 | Nginx |
| 容器化 | Docker Compose (6 服务) |

## 快速开始

```powershell
# 1. 克隆项目
git clone https://github.com/wow-wogua/viral-video-agent.git
cd viral-video-agent

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key

# 3. 启动服务
docker compose up -d

# 4. 访问
# 前端页面：http://localhost
# 后端 API：http://localhost:8000
# MCP Server：http://localhost:8001
```

### 使用微调模型（可选）

Researcher Agent 可以将 LoRA 微调后的 Qwen3-4B 作为 MiMo API 的本地 A/B 路径。内置 50 条工具调用评测中准确率从 88% 提升至 94%、完全准确率从 54% 提升至 80%；但当前以 `base + direct adapter` 为主口径的 hard44/holdout20 公平实验没有形成稳定基座优势，因此默认链路仍使用 API 模型，不把微调模型描述为生产替代。

```bash
# 终端1：启动微调模型 API（需要先训练，见 tool-calling-finetune 项目）
cd D:\internship\tool-calling-finetune
python scripts\serve_model.py

# 终端2：启动项目2，启用微调模型
cd D:\internship\viral-video-agent
$env:USE_FINETUNED_MODEL="true"
$env:FINETUNED_MODEL_URL="http://host.docker.internal:8002/v1"
docker compose up -d
```

只有 Researcher 使用微调模型，其他 Agent（Supervisor/Planner/Analyst/Writer）仍用 MiMo API。同一 hard44/holdout20 和相同生成参数下，direct adapter 在默认 Prompt 上低于基座；rules Prompt 只改善部分完全准确率，Safe 指标和最稳基座配置仍无稳定优势。旧 4-bit merged 产物与基座完全相同属于导出路径风险，已不再作为微调效果依据；本地服务现在默认直接加载 4-bit 基座 + adapter。

**关闭：**
- 终端1：Ctrl+C
- 终端2：`docker compose down`

## 评测数据与口径

`bfcl_eval.py` 是 **BFCL 风格自建工具选择评测**，不是官方 BFCL 榜单；`tau_bench.py` 是 **tau-bench-inspired 端到端冒烟检查**，不是官方 tau-bench。新结果与历史结果分开保留，不能把新评分规则追溯到旧数据。

| 指标 | 历史结果 / 当前边界 |
|------|------|
| 多 Agent vs 单 Agent | 3 条不同任务各单次运行，综合均值 +0.53；其中 simple +1.2、medium -0.2，不能概括成“复杂任务普遍提升” |
| LLM-as-Judge 评测框架 | 5 维度打分；当前支持温度 0、默认重复 3 次取均值，旧对比结果仍是单次历史试验 |
| BFCL 风格工具选择 | 2026-07-11 旧全工具集35条：工具名30/35、已标注参数14/31、完全14/35；暴露 `none` 过度调用与参数文案不稳定，未通过改旧题 Prompt 追分 |
| v2 能力范围路由 | 冻结 dev 21/23（91.3%）；独立 holdout 13/13。只评当前可用能力，不等同官方 BFCL 或开放域泛化 |
| 微调模型工具准确率 | 内置50条历史为88%→94%；direct adapter在默认Prompt下低于基座，rules Prompt仅部分指标改善且Safe无稳定优势；旧4-bit merged结果仅作导出风险诊断 |
| tau-bench-inspired 冒烟检查 | 2026-07-11 当前严格18条为13/18（72.2%）：simple 3/3、medium 3/3、complex 5/5、edge 2/7；5条边界失败均为安全短路后缺少 `plan`，通过用例平均161.8秒。历史18/18只作旧规则记录 |
| RAG 来源 Recall@5 | 40 篇、235 个标题感知 chunk；2026-07-12 固定集28/28命中，来源审计通过。这是自建固定集，不代表开放域泛化 |
| v1/v2 架构 A/B | B站科技：164.8s→79.4s、LLM 16→7；B站美食+RAG：179.6s→119.4s、LLM 14→6。两组均 completed，报告长度同量级；仍需扩大任务集评估质量 |
| Redis 用户隔离 | 已验证 owner 可见、其他 `user_id` 返回 not_found，用户历史列表互不混合；这是客户端稳定ID隔离，不等同于登录鉴权 |
| FallbackCounter | 历史 JSON 82%、正则 18%，当前请求隔离实现更新后待重跑 |

## 项目结构

```
viral-video-agent/
├── src/
│   ├── agents/          # 5 个 Agent（supervisor/planner/researcher/analyst/writer）
│   ├── graph/           # LangGraph StateGraph 编排
│   ├── tools/           # MCP 工具（B站搜索/RAG检索/语音转写/趋势数据）
│   ├── gateway/         # LLM 网关（多 Provider + 成本追踪）
│   ├── prompts/         # Prompt 配置化（prompts.yaml + PromptManager）
│   ├── eval/            # 自建评测（BFCL风格/tau-inspired/LLM-as-Judge）
│   ├── utils/           # FallbackCounter + TraceTracker
│   ├── memory/          # 长期记忆（ChromaDB）
│   ├── rag/             # RAG 检索
│   ├── mcp/             # MCP Client
│   └── api/             # FastAPI 路由
├── frontend/            # Next.js 前端
├── knowledge/           # RAG 知识库（40 篇，5 分类，带来源与时间元数据）
├── docker-compose.yml   # 6 服务编排
├── Dockerfile           # 后端镜像
└── nginx.conf           # Nginx 反向代理
```
