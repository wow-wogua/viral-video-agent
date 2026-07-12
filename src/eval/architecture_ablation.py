"""用同一真实任务对比 v1/v2 图的质量、证据、LLM调用和耗时。"""

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from src.api.status import result_status
from src.graph.builder import build_graph
from src.utils.trace_tracker import trace_tracker


CASES = [
    {
        "id": "bilibili_tech",
        "query": "分析B站科技区最近的爆款视频，总结选题和标题规律",
        "platforms": ["bilibili"],
        "expected_status": "completed",
    },
    {
        "id": "bilibili_food_knowledge",
        "query": "分析B站美食区热门视频，并结合知识库方法论给出建议",
        "platforms": ["bilibili"],
        "expected_status": "completed",
    },
    {
        "id": "unsupported_douyin_search",
        "query": "搜索抖音最近的热门科技视频样本",
        "platforms": ["douyin"],
        "expected_status": "partial",
    },
]


async def run_case(version: str, case: dict) -> dict:
    trace_tracker.reset()
    graph = build_graph(version)
    started = time.perf_counter()
    result = await graph.ainvoke(
        {
            "user_id": f"architecture-ablation-{version}",
            "user_request": case["query"],
            "platforms": case["platforms"],
            "workflow_version": version,
            "task_complete": False,
            "data_sufficient": False,
            "analysis_confidence": 0.0,
            "report_final": "",
        },
        config={
            "configurable": {"thread_id": f"{version}-{case['id']}"},
            "recursion_limit": 50,
        },
    )
    elapsed_s = round(time.perf_counter() - started, 1)
    status, termination_reason = result_status(result)
    trace = trace_tracker.get_summary()
    evidence = result.get("evidence", [])
    return {
        "version": version,
        "case_id": case["id"],
        "status": status,
        "expected_status": case["expected_status"],
        "passed": status == case["expected_status"],
        "termination_reason": termination_reason,
        "elapsed_s": elapsed_s,
        "llm_calls": trace["total_llm_calls"],
        "supervisor_rounds": result.get("supervisor_rounds", 0),
        "plan_steps": len(result.get("plan", [])),
        "research_tasks": len(result.get("research_tasks", [])),
        "tool_statuses": [item.get("status") for item in result.get("tool_results", [])],
        "evidence_items": sum(item.get("sample_count", 0) for item in evidence),
        "evidence_sources": sorted({source for item in evidence for source in item.get("sources", [])}),
        "raw_data_count": len(result.get("raw_data", [])),
        "analysis_iterations": result.get("analysis_iterations", 0),
        "writer_revisions": result.get("report_revision_count", 0),
        "report_length": len(result.get("report_final", "")),
        "trace": trace,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", nargs="+", choices=["v1", "v2"], default=["v1", "v2"])
    parser.add_argument("--case-ids", nargs="+", help="只运行指定 case id")
    parser.add_argument("--output", help="结果 JSON；默认写入 src/eval/results")
    args = parser.parse_args()

    cases = CASES
    if args.case_ids:
        selected = set(args.case_ids)
        cases = [case for case in CASES if case["id"] in selected]
    if not cases:
        raise ValueError("没有选中评测用例")

    results = []
    for version in args.versions:
        for case in cases:
            print(f"运行 {version} / {case['id']}")
            results.append(await run_case(version, case))
            print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    payload = {
        "timestamp": datetime.now().isoformat(),
        "versions": args.versions,
        "cases": [case["id"] for case in cases],
        "results": results,
    }
    output = Path(args.output) if args.output else Path(
        f"src/eval/results/architecture_ablation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果已保存: {output}")


if __name__ == "__main__":
    asyncio.run(main())
