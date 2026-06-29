"""
多Agent vs 单Agent 对比实验
============================
跑相同测试用例，对比 5-Agent 方案和单 Agent Baseline 的质量/成本/延迟。

用法:
    python -m src.eval.compare_experiment --limit 3
    python -m src.eval.compare_experiment --cases tau --limit 5
"""

import asyncio
import json
import sys
import time
import argparse

from src.graph.builder import build_graph
from src.eval.single_agent_baseline import run_single_agent
from src.eval.llm_judge_eval import judge_report, JUDGE_DIMENSIONS
from src.gateway.cost_tracker import cost_tracker

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 对比实验用例（从 tau-bench 选取代表性用例）
COMPARE_CASES = [
    {"id": "cmp-01", "query": "分析B站当前热门视频的内容特征和爆款规律", "category": "simple"},
    {"id": "cmp-02", "query": "分析B站科技区最近的爆款视频，找出涨粉规律", "category": "medium"},
    {"id": "cmp-03", "query": "对比B站游戏区和生活区的爆款视频差异，给出跨分区运营策略", "category": "complex"},
    {"id": "cmp-04", "query": "分析B站美妆区和美食区的爆款差异，给出跨分区内容策略", "category": "complex"},
    {"id": "cmp-05", "query": "帮我想想办法", "category": "edge"},
]


async def run_multi_agent(query: str) -> dict:
    """跑 5-Agent 方案。"""
    cost_tracker.reset()
    start_time = time.time()
    graph = build_graph()

    result = await graph.ainvoke(
        {
            "user_request": query,
            "task_complete": False,
            "data_sufficient": False,
            "analysis_confidence": 0.0,
            "report_final": "",
        },
        config={"configurable": {"thread_id": f"cmp-multi-{hash(query)}"}, "recursion_limit": 50},
    )

    latency = time.time() - start_time
    cost = cost_tracker.get_summary()

    return {
        "report": result.get("report_final", ""),
        "report_length": len(result.get("report_final", "")),
        "latency_s": round(latency, 1),
        "cost": cost,
        "supervisor_rounds": result.get("supervisor_rounds", 0),
        "analysis_iterations": result.get("analysis_iterations", 0),
        "report_revision_count": result.get("report_revision_count", 0),
        "raw_data_count": len(result.get("raw_data", [])),
    }


async def run_experiment(cases: list, limit: int = None) -> dict:
    """跑对比实验。"""
    if limit:
        cases = cases[:limit]

    total = len(cases)
    print(f"多Agent vs 单Agent 对比实验")
    print(f"用例数: {total}")
    print()

    multi_results = []
    single_results = []

    for i, case in enumerate(cases):
        query = case["query"]
        print(f"\n{'='*60}")
        print(f"[{i+1}/{total}] {case.get('category', '?')}: {query}")
        print(f"{'='*60}")

        # 跑多 Agent
        print(f"  [多Agent] 运行中...")
        try:
            multi = await run_multi_agent(query)
            print(f"  [多Agent] 报告:{multi['report_length']}字 耗时:{multi['latency_s']}s Token:{multi['cost']['input_tokens']}+{multi['cost']['output_tokens']}")
        except Exception as e:
            print(f"  [多Agent] ERROR: {e}")
            multi = {"error": str(e), "report": "", "latency_s": 0, "cost": {"input_tokens": 0, "output_tokens": 0, "total_cost": 0}}

        # 跑单 Agent
        print(f"  [单Agent] 运行中...")
        try:
            single = await run_single_agent(query)
            print(f"  [单Agent] 报告:{single['report_length']}字 耗时:{single['latency_s']}s Token:{single['cost']['input_tokens']}+{single['cost']['output_tokens']}")
        except Exception as e:
            print(f"  [单Agent] ERROR: {e}")
            single = {"error": str(e), "report": "", "latency_s": 0, "cost": {"input_tokens": 0, "output_tokens": 0, "total_cost": 0}}

        # LLM-as-Judge 评分
        if multi.get("report") and single.get("report"):
            print(f"  [Judge] 评分中...")
            multi_scores = await judge_report(query, multi["report"], [], [])
            single_scores = await judge_report(query, single["report"], [], [])

            multi_avg = sum(v["score"] for v in multi_scores.values() if isinstance(v, dict) and v.get("score", 0) > 0) / max(len(multi_scores), 1)
            single_avg = sum(v["score"] for v in single_scores.values() if isinstance(v, dict) and v.get("score", 0) > 0) / max(len(single_scores), 1)

            print(f"  [结果] 多Agent: {multi_avg:.1f}/5 | 单Agent: {single_avg:.1f}/5 | 差值: {multi_avg - single_avg:+.1f}")
        else:
            multi_scores = {}
            single_scores = {}
            multi_avg = 0
            single_avg = 0

        multi_results.append({"case_id": case["id"], "scores": multi_scores, "avg_score": round(multi_avg, 2), **{k: v for k, v in multi.items() if k != "report"}})
        single_results.append({"case_id": case["id"], "scores": single_scores, "avg_score": round(single_avg, 2), **{k: v for k, v in single.items() if k != "report"}})

        if i < total - 1:
            await asyncio.sleep(2)

    # 汇总
    multi_avg_score = sum(r["avg_score"] for r in multi_results) / len(multi_results) if multi_results else 0
    single_avg_score = sum(r["avg_score"] for r in single_results) / len(single_results) if single_results else 0
    multi_avg_latency = sum(r.get("latency_s", 0) for r in multi_results) / len(multi_results) if multi_results else 0
    single_avg_latency = sum(r.get("latency_s", 0) for r in single_results) / len(single_results) if single_results else 0
    multi_avg_tokens = sum(r.get("cost", {}).get("input_tokens", 0) + r.get("cost", {}).get("output_tokens", 0) for r in multi_results) / len(multi_results) if multi_results else 0
    single_avg_tokens = sum(r.get("cost", {}).get("input_tokens", 0) + r.get("cost", {}).get("output_tokens", 0) for r in single_results) / len(single_results) if single_results else 0

    comparison = {
        "cases": total,
        "multi_agent": {
            "avg_score": round(multi_avg_score, 2),
            "avg_latency_s": round(multi_avg_latency, 1),
            "avg_tokens": round(multi_avg_tokens),
            "details": multi_results,
        },
        "single_agent": {
            "avg_score": round(single_avg_score, 2),
            "avg_latency_s": round(single_avg_latency, 1),
            "avg_tokens": round(single_avg_tokens),
            "details": single_results,
        },
        "delta": {
            "score": round(multi_avg_score - single_avg_score, 2),
            "latency_s": round(multi_avg_latency - single_avg_latency, 1),
            "tokens": round(multi_avg_tokens - single_avg_tokens),
        },
    }

    print(f"\n{'='*60}")
    print(f"对比实验结果")
    print(f"{'='*60}")
    print(f"{'指标':<16} {'多Agent':>10} {'单Agent':>10} {'差值':>10}")
    print(f"{'-'*46}")
    print(f"{'平均分 (1-5)':<16} {multi_avg_score:>10.2f} {single_avg_score:>10.2f} {multi_avg_score-single_avg_score:>+10.2f}")
    print(f"{'平均耗时 (s)':<16} {multi_avg_latency:>10.1f} {single_avg_latency:>10.1f} {multi_avg_latency-single_avg_latency:>+10.1f}")
    print(f"{'平均 Token':<16} {multi_avg_tokens:>10.0f} {single_avg_tokens:>10.0f} {multi_avg_tokens-single_avg_tokens:>+10.0f}")
    print(f"{'='*60}")

    # 保存结果
    out_file = f"src/eval/results/compare_experiment_{time.strftime('%Y%m%d_%H%M%S')}.json"
    import os
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)
    print(f"结果已保存到: {out_file}")

    return comparison


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="多Agent vs 单Agent 对比实验")
    parser.add_argument("--limit", type=int, help="只跑前 N 条")
    parser.add_argument("--cases", type=str, help="'tau' 使用 tau-bench 18 条，或自定义 JSON 文件")
    args = parser.parse_args()

    cases = COMPARE_CASES
    if args.cases == "tau":
        from src.eval.tau_bench import E2E_CASES
        cases = [{"id": f"tau-{i+1:02d}", "query": c["query"], "category": c.get("category", "?")} for i, c in enumerate(E2E_CASES)]

    asyncio.run(run_experiment(cases, limit=args.limit))
