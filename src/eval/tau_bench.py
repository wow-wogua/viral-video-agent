import asyncio
import json
import sys
import time
from src.graph.builder import build_graph

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# tau-bench 评测集：18 条，覆盖简单(3)/中等(3)/复杂(5)/边界(7) 4 类任务
E2E_CASES = [
    # ── 简单任务（单步）──
    {
        "query": "分析B站当前热门视频的内容特征和爆款规律",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "report_final"],
        "check_rules": ["report_final length > 200", "plan has >= 2 steps"],
        "category": "simple",
    },
    {
        "query": "分析B站热门视频的选题方向和时长分布",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "report_final"],
        "check_rules": ["report_final length > 200"],
        "category": "simple",
    },
    {
        "query": "分析B站最近的热门视频，总结爆款特征",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "report_final"],
        "check_rules": ["report_final length > 200", "plan has >= 2 steps"],
        "category": "simple",
    },

    # ── 中等任务（需要关键词过滤）──
    {
        "query": "分析B站科技区最近的爆款视频，找出涨粉规律",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "raw_data", "analysis", "report_final"],
        "check_rules": ["raw_data not empty", "analysis has confidence"],
        "category": "medium",
    },
    {
        "query": "分析B站美食区热门视频的封面设计和标题套路",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "raw_data", "analysis", "report_final"],
        "check_rules": ["raw_data not empty", "report_final length > 500"],
        "category": "medium",
    },
    {
        "query": "分析B站游戏区最近的爆款视频，找出内容规律",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "raw_data", "analysis", "report_final"],
        "check_rules": ["raw_data not empty", "report_final length > 300"],
        "category": "medium",
    },

    # ── 复杂任务（需要多轮分析）──
    {
        "query": "对比B站游戏区和生活区的爆款视频差异，给出跨分区运营策略",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "raw_data", "analysis", "report_final"],
        "check_rules": ["plan has >= 4 steps", "analysis_iterations >= 1"],
        "category": "complex",
    },
    {
        "query": "分析B站最近一周的热门视频，从内容、数据、形式三个维度总结爆款规律",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "raw_data", "analysis", "report_final"],
        "check_rules": ["plan has >= 3 steps", "report_final length > 800"],
        "category": "complex",
    },
    {
        "query": "分析B站美妆区和美食区的爆款差异，给出跨分区内容策略",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "raw_data", "analysis", "report_final"],
        "check_rules": ["plan has >= 4 steps", "raw_data not empty"],
        "category": "complex",
    },
    {
        "query": "分析B站科技区最近的爆款，结合知识库里的行业方法论给出内容建议",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "raw_data", "analysis", "report_final"],
        "check_rules": ["raw_data not empty", "report_final length > 500"],
        "category": "complex",
    },
    {
        "query": "分析B站知识区和生活区的爆款视频差异，从选题、封面、时长三个维度对比",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "raw_data", "analysis", "report_final"],
        "check_rules": ["plan has >= 3 steps", "analysis_iterations >= 1"],
        "category": "complex",
    },

    # ── 边界任务（模糊需求 / 异常输入）──
    {
        "query": "帮我想想办法",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "report_final"],
        "check_rules": ["report_final not empty"],
        "category": "edge",
    },
    {
        "query": "看看有什么可以分析的",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "report_final"],
        "check_rules": ["report_final not empty"],
        "category": "edge",
    },
    {
        "query": "分析一个不存在的分区的爆款视频",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "report_final"],
        "check_rules": ["report_final not empty"],
        "category": "edge",
    },
    {
        "query": "搜索抖音视频",
        "platforms": ["douyin"],
        "expect_fields": ["plan", "report_final"],
        "check_rules": ["report_final not empty"],
        "category": "edge",
    },
    {
        "query": "什么都不分析",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "report_final"],
        "check_rules": ["report_final not empty"],
        "category": "edge",
    },
    {
        "query": "给我分析一下",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "report_final"],
        "check_rules": ["report_final not empty"],
        "category": "edge",
    },
    {
        "query": "",
        "platforms": ["bilibili"],
        "expect_fields": ["plan", "report_final"],
        "check_rules": ["report_final not empty"],
        "category": "edge",
    },
]


def check_rule(rule: str, result: dict) -> bool:
    """检查单条规则是否满足。"""
    if rule == "report_final length > 200":
        return len(result.get("report_final", "")) > 200
    if rule == "report_final length > 500":
        return len(result.get("report_final", "")) > 500
    if rule == "report_final length > 800":
        return len(result.get("report_final", "")) > 800
    if rule == "report_final not empty":
        return bool(result.get("report_final"))
    if rule == "plan has >= 2 steps":
        return len(result.get("plan", [])) >= 2
    if rule == "plan has >= 3 steps":
        return len(result.get("plan", [])) >= 3
    if rule == "plan has >= 4 steps":
        return len(result.get("plan", [])) >= 4
    if rule == "raw_data not empty":
        return bool(result.get("raw_data"))
    if rule == "analysis has confidence":
        return result.get("analysis_confidence", 0) > 0
    if rule == "analysis_iterations >= 1":
        return result.get("analysis_iterations", 0) >= 1
    return True  # 未知规则默认通过


async def eval_e2e():
    """评估端到端任务成功率（tau-bench 范式）+ 性能指标。"""
    graph = build_graph()
    success = 0
    total = len(E2E_CASES)
    all_results = []

    for i, case in enumerate(E2E_CASES):
        print(f"\n{'='*50}")
        print(f"测试 {i+1}/{total} [{case['category']}]: {case['query']}")
        print(f"{'='*50}")

        start_time = time.time()
        try:
            result = await graph.ainvoke(
                {
                    "user_request": case["query"],
                    "task_complete": False,
                    "data_sufficient": False,
                    "analysis_confidence": 0.0,
                    "report_final": "",
                },
                config={
                    "configurable": {"thread_id": f"eval-{i}"},
                    "recursion_limit": 50,
                },
            )
            latency = time.time() - start_time

            # 检查必需字段
            fields_ok = True
            for field in case["expect_fields"]:
                if not result.get(field):
                    print(f"  [FAIL] 缺少字段: {field}")
                    fields_ok = False

            # 检查规则
            rules_ok = True
            for rule in case.get("check_rules", []):
                if not check_rule(rule, result):
                    print(f"  [FAIL] 规则未满足: {rule}")
                    rules_ok = False

            case_pass = fields_ok and rules_ok
            if case_pass:
                success += 1
                print(f"  [PASS] 通过")
            else:
                print(f"  [FAIL] 失败")

            all_results.append({
                "case": i + 1,
                "query": case["query"],
                "category": case["category"],
                "latency_s": round(latency, 1),
                "passed": case_pass,
                "supervisor_rounds": result.get("supervisor_rounds", 0),
                "analysis_iterations": result.get("analysis_iterations", 0),
                "report_revision_count": result.get("report_revision_count", 0),
                "report_length": len(result.get("report_final", "")),
                "plan_steps": len(result.get("plan", [])),
            })

        except Exception as e:
            latency = time.time() - start_time
            print(f"  [FAIL] 异常: {e}")
            all_results.append({
                "case": i + 1,
                "query": case["query"],
                "category": case["category"],
                "latency_s": round(latency, 1),
                "passed": False,
                "error": str(e),
            })

    # 汇总
    rate = success / total * 100
    passed_results = [r for r in all_results if r.get("passed")]

    print(f"\n{'='*60}")
    print(f"端到端任务成功率: {success}/{total} ({rate:.1f}%)")
    if passed_results:
        avg_latency = sum(r["latency_s"] for r in passed_results) / len(passed_results)
        avg_rounds = sum(r.get("supervisor_rounds", 0) for r in passed_results) / len(passed_results)
        avg_iterations = sum(r.get("analysis_iterations", 0) for r in passed_results) / len(passed_results)
        avg_revisions = sum(r.get("report_revision_count", 0) for r in passed_results) / len(passed_results)
        print(f"平均耗时: {avg_latency:.1f}s ({avg_latency/60:.1f}min)")
        print(f"平均 Supervisor 轮数: {avg_rounds:.1f}")
        print(f"平均 Analyst 迭代次数: {avg_iterations:.1f}")
        print(f"平均 Writer 修订次数: {avg_revisions:.1f}")
    print(f"{'='*60}")

    summary = {
        "success": success,
        "total": total,
        "success_rate": rate,
        "details": all_results,
    }
    if passed_results:
        summary["avg_latency_s"] = round(sum(r["latency_s"] for r in passed_results) / len(passed_results), 1)
        summary["avg_supervisor_rounds"] = round(sum(r.get("supervisor_rounds", 0) for r in passed_results) / len(passed_results), 1)
        summary["avg_analysis_iterations"] = round(sum(r.get("analysis_iterations", 0) for r in passed_results) / len(passed_results), 1)
        summary["avg_report_revision_count"] = round(sum(r.get("report_revision_count", 0) for r in passed_results) / len(passed_results), 1)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    asyncio.run(eval_e2e())
