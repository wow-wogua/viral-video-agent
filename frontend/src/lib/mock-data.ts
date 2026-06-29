export interface CostInfo {
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
}

export interface AgentTrace {
  agent: string;
  duration_s: number;
  llm_calls: number;
  pct_of_total: number;
}

export interface TraceInfo {
  total_duration_s: number;
  total_llm_calls: number;
  agents: AgentTrace[];
}

export interface FallbackInfo {
  total: number;
  by_layer: { json: number; regex: number; inference: number; default: number };
  json_rate: number;
  regex_rate: number;
  inference_rate: number;
}

export interface AnalysisRecord {
  id: string;
  title: string;
  platform: string;
  date: string;
  status: 'completed' | 'running' | 'error';
  plan: string[];
  report: string;
  cost?: CostInfo;
  trace?: TraceInfo;
  fallback?: FallbackInfo;
  prompt_version?: string;
}

export const mockRecords: AnalysisRecord[] = [
  {
    id: '1',
    title: 'B站当前热门视频内容特征分析',
    platform: 'bilibili',
    date: '2025-06-07',
    status: 'completed',
    plan: [
      '1. 获取B站当前热门排行榜数据',
      '2. 分析热门视频的内容类型分布',
      '3. 提炼爆款规律',
      '4. 生成报告',
    ],
    report: `# B站热门视频内容特征分析报告

> 数据来源：B站全站热门排行榜 TOP100 | 分析日期：2025-06-07

## 执行摘要

当前B站热门视频呈现三个核心特征：**生活日常类占比最高（35%）**、**60-120秒是黄金时长**、**标题悬念式钩子完播率最高**。

## 核心发现

### 发现一：内容类型分布

| 内容类型 | 占比 | 平均点赞 |
|----------|------|----------|
| 生活日常 | 35% | 15.2万 |
| 知识科普 | 25% | 12.8万 |
| 搞笑娱乐 | 20% | 18.5万 |
| 美食 | 10% | 11.3万 |
| 其他 | 10% | 8.7万 |

### 发现二：时长分布

| 时长区间 | 占比 | 平均完播率 |
|----------|------|-----------|
| 30-60秒 | 25% | 38% |
| 60-120秒 | 45% | 42% |
| 120-300秒 | 25% | 35% |
| 300秒以上 | 5% | 28% |

### 发现三：标题钩子类型

- **悬念式**（"你猜结果怎么样？"）：占比 40%
- **数字式**（"3个方法让你..."）：占比 30%
- **痛点式**（"为什么你总是..."）：占比 20%
- **其他**：占比 10%

## 爆款规律

\`\`\`
爆款公式 = 热门话题 + 悬念钩子 + 60-120秒时长 + 每5秒一个信息点
\`\`\`

## 策略建议

1. **选题方向**：优先做生活日常和知识科普类内容
2. **时长控制**：控制在 60-120 秒
3. **钩子设计**：前 3 秒用悬念式钩子
4. **发布频率**：保持每周 3-5 条更新

> 注：当前数据来源为B站全站热门排行榜，不支持按关键词搜索。`,
  },
  {
    id: '2',
    title: 'B站热门视频选题方向分析',
    platform: 'bilibili',
    date: '2025-06-06',
    status: 'completed',
    plan: [
      '1. 获取B站热门排行榜数据',
      '2. 按内容类型分类统计',
      '3. 分析各类型的爆款特征',
      '4. 生成报告',
    ],
    report: `# B站热门视频选题方向分析

## 执行摘要

热门视频选题以**生活记录**和**实用知识**为主，用户偏好真实、有信息量的内容。

## 核心发现

1. 生活日常类占比最高，真实感是核心竞争力
2. 知识科普类增长最快，专业人设更容易建立信任
3. 搞笑娱乐类点赞最高，但粉丝粘性较低

## 策略建议

1. 优先做"有信息量"的内容
2. 控制时长在 60-120 秒
3. 标题用悬念式钩子

> 注：数据来源为B站全站热门排行榜。`,
  },
];
