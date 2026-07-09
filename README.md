# 爆款视频分析多智能体系统

基于 LangGraph 的 5-Agent 协作系统，自动分析短视频平台爆款视频，提炼爆款规律并生成策略报告。

## 架构

```
用户输入 → Supervisor → Planner → Researcher → Analyst → Writer → 报告
              ↑            ↓          ↓            ↓         ↓
              └────────────┴──────────┴────────────┴─────────┘
                    所有节点回到 Supervisor（集中路由）
```

**核心设计：**
- Supervisor 集中路由 + 意图分类（非分析请求直接回答）+ 三层兜底解析（JSON→正则→状态推断）
- Researcher LLM 驱动工具选择，通过 MCP 协议调用工具
- Analyst 自评循环（默认置信度阈值 0.8，可用环境变量调整）+ Writer 修订循环
- 长期记忆系统（ChromaDB），支持跨会话复用
- RAG 检索平台过滤（B站/抖音/快手自动识别）

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
| 缓存 | Redis |
| 反向代理 | Nginx |
| 容器化 | Docker Compose (6 服务) |

## 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/wow-wogua/viral-video-agent.git
cd viral-video-agent

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key

# 3. 启动服务
docker-compose up -d

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
set USE_FINETUNED_MODEL=true
set FINETUNED_MODEL_URL=http://host.docker.internal:8002/v1
docker-compose up -d
```

只有 Researcher 使用微调模型，其他 Agent（Supervisor/Planner/Analyst/Writer）仍用 MiMo API。

**关闭：**
- 终端1：Ctrl+C
- 终端2：`docker-compose down`

## 评测数据

| 指标 | 结果 |
|------|------|
| 多 Agent vs 单 Agent | 复杂任务 +0.53 分（+0.6~1.2） |
| LLM-as-Judge 评测框架 | 5 维度打分（完整性/准确性/可操作性/数据利用/综合） |
| BFCL 工具调用准确率 | 90.0%（30 条，MiMo API） |
| 微调模型工具准确率 | 94.0%（50 条内置评测，Qwen3-4B SFT+DPO）；hard eval / holdout 用于误差分析，未证明自然表达边界提升 |
| tau-bench 端到端成功率 | 100%（18 条） |
| RAG 检索命中率 | 67.9%（28 条） |
| 单次分析耗时 | 2.6 分钟 |
| FallbackCounter | JSON 解析 82%、正则兜底 18% |

## 项目结构

```
viral-video-agent/
├── src/
│   ├── agents/          # 5 个 Agent（supervisor/planner/researcher/analyst/writer）
│   ├── graph/           # LangGraph StateGraph 编排
│   ├── tools/           # MCP 工具（B站搜索/RAG检索/语音转写/趋势数据）
│   ├── gateway/         # LLM 网关（多 Provider + 成本追踪）
│   ├── prompts/         # Prompt 配置化（prompts.yaml + PromptManager）
│   ├── eval/            # 评测体系（BFCL/tau-bench/LLM-as-Judge）
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
