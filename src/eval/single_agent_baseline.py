"""
单 Agent Baseline
=================
单 Agent + 大 Prompt，不用 LangGraph，直接一个函数调 LLM 完成所有任务。
用于和 5-Agent 方案做对比实验。

用法:
    python -m src.eval.single_agent_baseline --query "分析B站当前热门视频的内容特征和爆款规律"
    python -m src.eval.single_agent_baseline --cases tau   # 跑 tau-bench 18 条
"""

import asyncio
import json
import sys
import time
import argparse

from langchain_core.messages import HumanMessage
from src.agents.supervisor import get_llm, extract_text
from src.tools.search import search_videos
from src.gateway.cost_tracker import cost_tracker

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SINGLE_AGENT_PROMPT = """你是一个短视频爆款分析专家。请根据用户需求完成以下所有任务：

## 用户需求
{query}

## 你的任务
1. **数据采集**：根据需求，调用 search_videos 获取 B 站视频数据
2. **多维分析**：从内容、数据、形式、平台四个维度分析数据
3. **报告生成**：输出一份完整的策略报告

## 可用工具
- search_videos(keyword, platforms, limit): 搜索视频数据

## 输出要求
请直接输出完整报告，以 # 爆款视频策略报告 开头，包含：
- ## 执行摘要
- ## 核心发现（含数据表格）
- ## 爆款规律
- ## 策略建议（具体可执行）
- ## 数据附录

不要输出任何解释或讨论，直接输出报告正文。"""


async def run_single_agent(query: str) -> dict:
    """单 Agent 执行：先搜数据，再生成报告。"""
    cost_tracker.reset()
    start_time = time.time()

    # 1. 搜索数据
    try:
        raw_data = await search_videos(keyword=query, platforms=["bilibili"], limit=10)
    except Exception as e:
        print(f"  [WARN] 搜索失败: {e}")
        raw_data = []

    # 2. 构建大 Prompt（包含数据）
    data_summary = ""
    if raw_data:
        for i, item in enumerate(raw_data[:10]):
            title = item.get("title", "无标题")
            views = item.get("view", item.get("play", "N/A"))
            likes = item.get("like", "N/A")
            data_summary += f"\n{i+1}. {title} | 播放:{views} | 点赞:{likes}"

    prompt = SINGLE_AGENT_PROMPT.format(query=query)
    if data_summary:
        prompt += f"\n\n## 已采集的数据\n{data_summary}"

    # 3. 调用 LLM 生成报告
    llm = get_llm()
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    report = extract_text(response)

    latency = time.time() - start_time
    cost = cost_tracker.get_summary()

    return {
        "report": report,
        "report_length": len(report),
        "raw_data_count": len(raw_data),
        "latency_s": round(latency, 1),
        "cost": cost,
    }


async def run_single_agent_cases(cases: list) -> list:
    """批量跑单 Agent 用例。"""
    results = []
    for i, case in enumerate(cases):
        query = case["query"] if isinstance(case, dict) else case
        print(f"\n[{i+1}/{len(cases)}] {query[:50]}...")
        try:
            result = await run_single_agent(query)
            print(f"  报告长度: {result['report_length']}字, 耗时: {result['latency_s']}s")
            results.append({"case_id": case.get("id", f"case-{i+1}") if isinstance(case, dict) else f"case-{i+1}", **result})
        except Exception as e:
            print(f"  [ERROR] {e}")
            results.append({"case_id": f"case-{i+1}", "error": str(e)})
        if i < len(cases) - 1:
            await asyncio.sleep(2)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="单 Agent Baseline")
    parser.add_argument("--query", type=str, help="单条查询")
    parser.add_argument("--cases", type=str, help="用例文件路径，或 'tau' 使用 tau-bench")
    args = parser.parse_args()

    if args.query:
        result = asyncio.run(run_single_agent(args.query))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cases == "tau":
        from src.eval.tau_bench import E2E_CASES
        results = asyncio.run(run_single_agent_cases(E2E_CASES))
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("请指定 --query 或 --cases tau")
