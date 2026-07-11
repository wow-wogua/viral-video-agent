# 爆款视频分析多智能体系统

基于 LangGraph 的 5-Agent 串行回环系统，自动分析短视频平台爆款视频，提炼爆款规律并生成策略报告。

## 架构

```
用户输入 → Supervisor → Planner → Researcher → Analyst → Writer → 报告
              ↑            ↓          ↓            ↓         ↓
              └────────────┴──────────┴────────────┴─────────┘
                    所有节点回到 Supervisor（集中路由）
```

**核心设计：**
- Supervisor 集中路由 + 意图分类（非分析请求直接回答）+ 三层兜底解析（JSON→正则→状态推断）
- Researcher LLM 驱动选择 `search_videos` / `rag_search` / `get_transcript` / `get_trend_data` / `none`，通过 MCP 调用并保留直接函数兜底
- `raw_data` 与搜索关键词使用 reducer 跨多步累积；Planner → Researcher → Analyst → Writer 存在数据依赖，当前不是扇出并行架构
- Analyst 自评循环（默认置信度阈值 0.8，可用环境变量调整）+ Writer 修订循环；达到最大迭代时保留真实置信度
- 请求携带稳定 `user_id`，长期记忆与 Redis 历史列表按用户隔离；Redis 只保存缓存、历史记录和 running/completed/partial/failed 状态，当前未接入 Celery
- CostTracker / TraceTracker / FallbackCounter 使用请求上下文隔离，避免并发请求串统计
- RAG 使用向量候选 + 中文词项扩展的轻量混合排序，按来源去重，并支持 B站/抖音/快手平台过滤
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

Researcher Agent 可以使用 LoRA 微调后的 Qwen3-4B 模型替代 MiMo API。内置 50 条工具调用评测中准确率从 88% 提升至 94%、完全准确率从 54% 提升至 80%；独立 hard eval / holdout 未证明自然表达边界提升，因此该模型当前作为 Researcher 的可选 A/B 路径，默认链路仍可继续使用 MiMo API。

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

只有 Researcher 使用微调模型，其他 Agent（Supervisor/Planner/Analyst/Writer）仍用 MiMo API。同一 hard44/holdout20、同一完整 Prompt 和相同生成参数的公平实验已经完成：SFT+DPO v3 与基座的对应汇总指标相同，没有证明微调泛化提升；显式路由规则只在 hard 集提高工具名准确率，却让 holdout 工具名准确率从 100% 降到 80%，因此当前不设为默认。

**关闭：**
- 终端1：Ctrl+C
- 终端2：`docker compose down`

## 评测数据与口径

`bfcl_eval.py` 是 **BFCL 风格自建工具选择评测**，不是官方 BFCL 榜单；`tau_bench.py` 是 **tau-bench-inspired 端到端冒烟检查**，不是官方 tau-bench。新结果与历史结果分开保留，不能把新评分规则追溯到旧数据。

| 指标 | 历史结果 / 当前边界 |
|------|------|
| 多 Agent vs 单 Agent | 3 条不同任务各单次运行，综合均值 +0.53；其中 simple +1.2、medium -0.2，不能概括成“复杂任务普遍提升” |
| LLM-as-Judge 评测框架 | 5 维度打分；当前支持温度 0、默认重复 3 次取均值，旧对比结果仍是单次历史试验 |
| BFCL 风格工具选择 | 2026-07-11 当前35条：工具名30/35（85.7%）、已标注参数14/31（45.2%）、完全14/35（40.0%）；主要问题是 `none` 过度调用与参数文案不稳定 |
| 微调模型工具准确率 | 内置50条历史为88%→94%；同 Prompt hard44/holdout20 公平实验中 SFT+DPO v3 与基座对应指标相同，未证明泛化提升 |
| tau-bench-inspired 冒烟检查 | 2026-07-11 当前严格18条为13/18（72.2%）：simple 3/3、medium 3/3、complex 5/5、edge 2/7；5条边界失败均为安全短路后缺少 `plan`，通过用例平均161.8秒。历史18/18只作旧规则记录 |
| RAG 来源 Recall@5 | 2026-07-11 当前固定集：27/27可回答用例命中，另有1/28知识库覆盖缺口（小红书）；这是自建固定集，不代表开放域泛化 |
| 单次分析耗时 | 当前真实同步 API 样例152.2秒；受 API、网络、Agent迭代次数和用例影响 |
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
├── knowledge/           # RAG 知识库（30 篇，5 分类）
├── docker-compose.yml   # 6 服务编排
├── Dockerfile           # 后端镜像
└── nginx.conf           # Nginx 反向代理
```
