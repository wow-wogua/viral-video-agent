import asyncio
import json
import sys
import time
import numpy as np
from src.graph.builder import build_graph

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# 性能评测用例：覆盖不同复杂度
PERF_CASES = [
    {"query": "分析B站热门视频的爆款规律", "complexity": "simple"},
    {"query": "分析B站科技区最近的爆款视频，找出涨粉规律", "complexity": "medium"},
    {"query": "分析B站美食区热门视频的封面设计和标题套路", "complexity": "medium"},
    {"query": "对比B站游戏区和生活区的爆款视频差异", "complexity": "complex"},
    {"query": "分析B站最近一周的热门视频，从内容、数据、形式三个维度总结爆款规律", "complexity": "complex"},
]


async def evaluate_performance():
    """评测系统性能指标：延迟、轮数、迭代次数。"""
    graph = build_graph()
    results = []

    for i, case in enumerate(PERF_CASES):
        print(f"\n[{i+1}/{len(PERF_CASES)}] {case['complexity']}: {case['query']}")

        start = time.time()
        try:
            result = await graph.ainvoke(
                {
                    "user_request": case["query"],
                    "platforms": ["bilibili"],
                    "task_complete": False,
                    "data_sufficient": False,
                    "analysis_confidence": 0.0,
                    "report_final": "",
                },
                config={
                    "configurable": {"thread_id": f"perf-{i}"},
                    "recursion_limit": 50,
                },
            )
            latency = time.time() - start

            entry = {
                "query": case["query"],
                "complexity": case["complexity"],
                "latency_s": round(latency, 1),
                "has_plan": bool(result.get("plan")),
                "has_report": bool(result.get("report_final")),
                "plan_steps": len(result.get("plan", [])),
                "supervisor_rounds": result.get("supervisor_rounds", 0),
                "analysis_iterations": result.get("analysis_iterations", 0),
                "report_revision_count": result.get("report_revision_count", 0),
                "report_length": len(result.get("report_final", "")),
            }
            print(f"  ✅ {latency:.1f}s | rounds={entry['supervisor_rounds']} | iter={entry['analysis_iterations']} | rev={entry['report_revision_count']}")
            results.append(entry)

        except Exception as e:
            latency = time.time() - start
            print(f"  ❌ 异常: {e}")
            results.append({
                "query": case["query"],
                "complexity": case["complexity"],
                "latency_s": round(latency, 1),
                "error": str(e),
            })

    # 汇总统计
    valid = [r for r in results if "error" not in r]
    if not valid:
        print("\n没有成功的测试用例")
        return

    latencies = [r["latency_s"] for r in valid]
    rounds_list = [r["supervisor_rounds"] for r in valid]
    iterations_list = [r["analysis_iterations"] for r in valid]
    revisions_list = [r["report_revision_count"] for r in valid]

    summary = {
        "total_cases": len(results),
        "success_cases": len(valid),
        "success_rate": f"{len(valid)}/{len(results)}",
        "latency": {
            "avg_s": round(np.mean(latencies), 1),
            "min_s": round(min(latencies), 1),
            "max_s": round(max(latencies), 1),
            "avg_min": round(np.mean(latencies) / 60, 1),
        },
        "supervisor_rounds": {
            "avg": round(np.mean(rounds_list), 1),
            "min": min(rounds_list),
            "max": max(rounds_list),
        },
        "analysis_iterations": {
            "avg": round(np.mean(iterations_list), 1),
            "min": min(iterations_list),
            "max": max(iterations_list),
        },
        "report_revision_count": {
            "avg": round(np.mean(revisions_list), 1),
            "min": min(revisions_list),
            "max": max(revisions_list),
        },
        "details": results,
    }

    print(f"\n{'='*60}")
    print("性能评测结果汇总")
    print(f"{'='*60}")
    print(f"成功率: {summary['success_rate']}")
    print(f"平均耗时: {summary['latency']['avg_s']}s ({summary['latency']['avg_min']}min)")
    print(f"耗时范围: {summary['latency']['min_s']}s ~ {summary['latency']['max_s']}s")
    print(f"平均 Supervisor 轮数: {summary['supervisor_rounds']['avg']}")
    print(f"平均 Analyst 迭代次数: {summary['analysis_iterations']['avg']}")
    print(f"平均 Writer 修订次数: {summary['report_revision_count']['avg']}")
    print(f"{'='*60}")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    asyncio.run(evaluate_performance())
