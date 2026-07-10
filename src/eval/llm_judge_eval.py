"""
LLM-as-Judge 评测框架
=====================
输入用例 JSON → 运行系统 → LLM-as-Judge 打分 → 输出结果 JSON

用法:
    # 跑内置用例
    python -m src.eval.llm_judge_eval

    # 跑自定义用例文件
    python -m src.eval.llm_judge_eval --cases src/eval/cases/custom_cases.json

    # 只跑前 N 条
    python -m src.eval.llm_judge_eval --limit 5

    # 指定输出文件
    python -m src.eval.llm_judge_eval --output results.json
"""

import asyncio
import json
import sys
import time
import argparse
from pathlib import Path

from src.graph.builder import build_graph
from src.agents.supervisor import get_llm, extract_text
from src.utils.fallback_counter import fallback_counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ─────────────────────────────────────────────
# 评测维度定义
# ─────────────────────────────────────────────

JUDGE_DIMENSIONS = {
    "completeness": {
        "name": "完整性",
        "description": "报告是否覆盖了用户需求的所有方面，是否有遗漏",
        "scale": "1=严重遗漏, 3=基本覆盖, 5=全面无遗漏",
    },
    "accuracy": {
        "name": "准确性",
        "description": "分析结论是否有数据支撑，逻辑是否自洽，有无明显错误",
        "scale": "1=多处错误, 3=基本准确, 5=完全准确",
    },
    "actionability": {
        "name": "可操作性",
        "description": "策略建议是否具体、可执行，而非泛泛而谈",
        "scale": "1=空泛无用, 3=有一定参考, 5=直接可执行",
    },
    "data_quality": {
        "name": "数据利用",
        "description": "是否有效利用了采集到的原始数据，数据引用是否合理",
        "scale": "1=未用数据, 3=部分引用, 5=数据驱动",
    },
    "overall": {
        "name": "综合评分",
        "description": "整体报告质量，作为面试项目展示的完成度",
        "scale": "1=不可用, 3=及格, 5=优秀",
    },
}

JUDGE_PROMPT_TEMPLATE = """你是一个严格的 AI 评测专家。请对以下"爆款视频分析系统"的输出进行评分。

## 用户需求
{query}

## 系统输出（报告）
{report}

## 执行计划
{plan}

## 原始数据（部分）
{raw_data_summary}

## 评分维度
{dimensions_desc}

## 评分规则
1. 每个维度打 1-5 分（整数）
2. 必须给出评分理由（1-2 句话）
3. 如果报告为空或明显无意义，所有维度给 1 分
4. 评分要严格：3 分代表"及格"，5 分代表"优秀"，不要通货膨胀

## 输出格式（严格 JSON）
{{
    "scores": {{
        "completeness": {{"score": 1-5, "reason": "..."}},
        "accuracy": {{"score": 1-5, "reason": "..."}},
        "actionability": {{"score": 1-5, "reason": "..."}},
        "data_quality": {{"score": 1-5, "reason": "..."}},
        "overall": {{"score": 1-5, "reason": "..."}}
    }},
    "summary": "一句话总评"
}}"""


# ─────────────────────────────────────────────
# 内置评测用例（可从外部 JSON 加载更多）
# ─────────────────────────────────────────────

BUILTIN_CASES = [
    {
        "id": "builtin-01",
        "query": "分析B站当前热门视频的内容特征和爆款规律",
        "category": "simple",
        "tags": ["bilibili", "全站"],
    },
    {
        "id": "builtin-02",
        "query": "分析B站科技区最近的爆款视频，找出涨粉规律",
        "category": "medium",
        "tags": ["bilibili", "科技"],
    },
    {
        "id": "builtin-03",
        "query": "对比B站游戏区和生活区的爆款视频差异，给出跨分区运营策略",
        "category": "complex",
        "tags": ["bilibili", "游戏", "生活", "对比"],
    },
    {
        "id": "builtin-04",
        "query": "分析B站美妆区和美食区的爆款差异，给出跨分区内容策略",
        "category": "complex",
        "tags": ["bilibili", "美妆", "美食", "对比"],
    },
    {
        "id": "builtin-05",
        "query": "帮我想想办法",
        "category": "edge",
        "tags": ["模糊需求"],
    },
]


# ─────────────────────────────────────────────
# 核心逻辑
# ─────────────────────────────────────────────

def _build_dimensions_desc() -> str:
    lines = []
    for key, dim in JUDGE_DIMENSIONS.items():
        lines.append(f"- **{dim['name']}**（{key}）：{dim['description']}。评分标准：{dim['scale']}")
    return "\n".join(lines)


def _summarize_raw_data(raw_data: list, max_items: int = 3) -> str:
    """截取前 N 条原始数据作为摘要，避免 Judge Prompt 过长。"""
    if not raw_data:
        return "（无原始数据）"
    summary_parts = []
    for item in raw_data[:max_items]:
        title = item.get("title", "无标题")
        views = item.get("view", item.get("play", "N/A"))
        likes = item.get("like", "N/A")
        summary_parts.append(f"  - {title} | 播放:{views} | 点赞:{likes}")
    if len(raw_data) > max_items:
        summary_parts.append(f"  - ... 共 {len(raw_data)} 条数据")
    return "\n".join(summary_parts)


async def _judge_once(query: str, report: str, plan: list, raw_data: list) -> dict:
    """以 temperature=0 完成一次 Judge 评分。"""
    llm = get_llm(temperature=0.0)

    prompt = JUDGE_PROMPT_TEMPLATE.format(
        query=query,
        report=report[:3000],  # 截断避免超长
        plan=json.dumps(plan, ensure_ascii=False)[:500],
        raw_data_summary=_summarize_raw_data(raw_data),
        dimensions_desc=_build_dimensions_desc(),
    )

    response = await llm.ainvoke([{"role": "user", "content": prompt}])
    text = extract_text(response)

    # 解析 JSON
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        result = json.loads(clean)
        return result.get("scores", {})
    except json.JSONDecodeError:
        # 正则兜底
        import re
        scores = {}
        for dim_key in JUDGE_DIMENSIONS:
            match = re.search(rf'"{dim_key}".*?"score"\s*:\s*(\d)', text, re.DOTALL)
            if match:
                scores[dim_key] = {"score": int(match.group(1)), "reason": "regex fallback"}
            else:
                scores[dim_key] = {"score": 0, "reason": "parse failed"}
        return scores


async def judge_report(
    query: str,
    report: str,
    plan: list,
    raw_data: list,
    repeats: int = 3,
) -> dict:
    """重复评分并按维度取均值。repeats=1 可复现早期单次试验。"""
    repeats = max(1, repeats)
    runs = []
    for _ in range(repeats):
        runs.append(await _judge_once(query, report, plan, raw_data))

    aggregated = {}
    for dim_key in JUDGE_DIMENSIONS:
        values = []
        reasons = []
        for run in runs:
            item = run.get(dim_key, {})
            score = item.get("score", 0) if isinstance(item, dict) else 0
            if score > 0:
                values.append(float(score))
                reason = item.get("reason", "")
                if reason:
                    reasons.append(reason)
        aggregated[dim_key] = {
            "score": round(sum(values) / len(values), 2) if values else 0,
            "reason": f"{repeats} 次评分均值。" + (reasons[0] if reasons else ""),
        }
    return aggregated


async def run_single_case(
    case: dict,
    graph,
    case_index: int,
    total: int,
    judge_repeats: int = 3,
) -> dict:
    """跑单条用例：运行系统 → 评分 → 返回结果。"""
    case_id = case.get("id", f"case-{case_index+1}")
    query = case["query"]
    category = case.get("category", "unknown")

    print(f"\n{'='*60}")
    print(f"[{case_index+1}/{total}] {category}: {query}")
    print(f"{'='*60}")

    # 1. 运行系统
    start_time = time.time()
    fallback_counter.reset()
    try:
        result = await graph.ainvoke(
            {
                "user_request": query,
                "platforms": case.get("platforms", ["bilibili"]),
                "task_complete": False,
                "data_sufficient": False,
                "analysis_confidence": 0.0,
                "report_final": "",
            },
            config={
                "configurable": {"thread_id": f"judge-{case_id}"},
                "recursion_limit": 50,
            },
        )
    except Exception as e:
        print(f"  [ERROR] 系统运行失败: {e}")
        return {
            "case_id": case_id,
            "query": query,
            "category": category,
            "status": "error",
            "error": str(e),
            "latency_s": round(time.time() - start_time, 1),
            "fallback": fallback_counter.get_summary(),
        }

    latency = time.time() - start_time
    report = result.get("report_final", "")
    plan = result.get("plan", [])
    raw_data = result.get("raw_data", [])
    fallback_summary = fallback_counter.get_summary()

    if not report:
        print(f"  [WARN] 报告为空")
        return {
            "case_id": case_id,
            "query": query,
            "category": category,
            "status": "no_report",
            "latency_s": round(latency, 1),
            "scores": {dim: {"score": 1, "reason": "报告为空"} for dim in JUDGE_DIMENSIONS},
            "supervisor_rounds": result.get("supervisor_rounds", 0),
            "analysis_iterations": result.get("analysis_iterations", 0),
            "report_length": 0,
            "fallback": fallback_summary,
        }

    # 2. LLM-as-Judge 评分
    print(f"  报告长度: {len(report)} 字, 耗时: {latency:.1f}s, 开始评分...")
    scores = await judge_report(query, report, plan, raw_data, repeats=judge_repeats)

    # 计算平均分
    valid_scores = [v["score"] for v in scores.values() if isinstance(v, dict) and v.get("score", 0) > 0]
    avg_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0

    print(f"  评分完成: 平均 {avg_score:.1f}/5")
    for dim_key, dim_info in JUDGE_DIMENSIONS.items():
        s = scores.get(dim_key, {})
        score_val = s.get("score", "?") if isinstance(s, dict) else "?"
        print(f"    {dim_info['name']}: {score_val}/5")

    return {
        "case_id": case_id,
        "query": query,
        "category": category,
        "status": "ok",
        "latency_s": round(latency, 1),
        "report_length": len(report),
        "plan_steps": len(plan),
        "raw_data_count": len(raw_data),
        "supervisor_rounds": result.get("supervisor_rounds", 0),
        "analysis_iterations": result.get("analysis_iterations", 0),
        "report_revision_count": result.get("report_revision_count", 0),
        "scores": scores,
        "avg_score": round(avg_score, 2),
        "fallback": fallback_summary,
    }


def _aggregate_results(results: list) -> dict:
    """汇总评测结果。"""
    ok_results = [r for r in results if r.get("status") == "ok"]
    error_results = [r for r in results if r.get("status") == "error"]
    no_report_results = [r for r in results if r.get("status") == "no_report"]

    if not ok_results:
        return {
            "total": len(results),
            "ok": 0,
            "errors": len(error_results),
            "no_report": len(no_report_results),
            "avg_score": 0,
        }

    # 按维度汇总
    dim_scores = {dim: [] for dim in JUDGE_DIMENSIONS}
    for r in ok_results:
        for dim in JUDGE_DIMENSIONS:
            s = r.get("scores", {}).get(dim, {})
            if isinstance(s, dict) and s.get("score", 0) > 0:
                dim_scores[dim].append(s["score"])

    dim_avgs = {}
    for dim, scores in dim_scores.items():
        if scores:
            dim_avgs[dim] = round(sum(scores) / len(scores), 2)
        else:
            dim_avgs[dim] = 0

    # 按 category 汇总
    categories = set(r.get("category", "unknown") for r in ok_results)
    cat_scores = {}
    for cat in categories:
        cat_results = [r for r in ok_results if r.get("category") == cat]
        cat_avg = sum(r["avg_score"] for r in cat_results) / len(cat_results) if cat_results else 0
        cat_scores[cat] = {
            "count": len(cat_results),
            "avg_score": round(cat_avg, 2),
        }

    overall_avg = sum(r["avg_score"] for r in ok_results) / len(ok_results)
    avg_latency = sum(r["latency_s"] for r in ok_results) / len(ok_results)

    # 汇总 fallback 统计
    total_fallback = {"json": 0, "regex": 0, "inference": 0, "default": 0}
    for r in results:
        fb = r.get("fallback", {}).get("by_layer", {})
        for layer in total_fallback:
            total_fallback[layer] += fb.get(layer, 0)
    fallback_total = sum(total_fallback.values())

    return {
        "total": len(results),
        "ok": len(ok_results),
        "errors": len(error_results),
        "no_report": len(no_report_results),
        "avg_score": round(overall_avg, 2),
        "avg_latency_s": round(avg_latency, 1),
        "dimension_averages": dim_avgs,
        "category_breakdown": cat_scores,
        "fallback_stats": {
            "total_parses": fallback_total,
            "by_layer": total_fallback,
            "json_rate": round(total_fallback["json"] / fallback_total, 3) if fallback_total else 0,
            "regex_rate": round(total_fallback["regex"] / fallback_total, 3) if fallback_total else 0,
            "inference_rate": round(total_fallback["inference"] / fallback_total, 3) if fallback_total else 0,
        },
    }


async def run_eval(
    cases: list = None,
    limit: int = None,
    output_path: str = None,
    judge_repeats: int = 3,
):
    """主评测入口。"""
    judge_repeats = max(1, judge_repeats)
    if cases is None:
        cases = BUILTIN_CASES
    if limit:
        cases = cases[:limit]

    total = len(cases)
    print(f"LLM-as-Judge 评测框架")
    print(f"用例数: {total}")
    print(f"评分维度: {', '.join(JUDGE_DIMENSIONS.keys())}")
    print(f"Judge 条件: temperature=0, 每份报告重复 {judge_repeats} 次取均值")
    print()

    graph = build_graph()
    results = []

    for i, case in enumerate(cases):
        result = await run_single_case(case, graph, i, total, judge_repeats=judge_repeats)
        results.append(result)
        # 避免限流
        if i < total - 1:
            await asyncio.sleep(2)

    # 汇总
    summary = _aggregate_results(results)

    output = {
        "meta": {
            "framework": "llm-judge-eval",
            "version": "1.0",
            "dimensions": list(JUDGE_DIMENSIONS.keys()),
            "total_cases": total,
            "judge_temperature": 0.0,
            "judge_repeats": judge_repeats,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "summary": summary,
        "cases": results,
    }

    # 输出
    print(f"\n{'='*60}")
    print(f"评测完成")
    print(f"  总用例: {summary['total']}")
    print(f"  成功: {summary['ok']}")
    print(f"  错误: {summary['errors']}")
    print(f"  无报告: {summary['no_report']}")
    if summary.get("avg_score"):
        print(f"  平均分: {summary['avg_score']}/5")
        print(f"  平均耗时: {summary['avg_latency_s']}s")
        print(f"  维度平均分:")
        for dim, avg in summary.get("dimension_averages", {}).items():
            print(f"    {JUDGE_DIMENSIONS[dim]['name']}: {avg}/5")
    fb = summary.get("fallback_stats", {})
    if fb.get("total_parses"):
        print(f"  兜底统计:")
        print(f"    总解析次数: {fb['total_parses']}")
        print(f"    JSON成功: {fb['by_layer']['json']} ({fb['json_rate']:.0%})")
        print(f"    正则兜底: {fb['by_layer']['regex']} ({fb['regex_rate']:.0%})")
        print(f"    状态推断: {fb['by_layer']['inference']} ({fb['inference_rate']:.0%})")
    print(f"{'='*60}")

    # 保存到文件
    if output_path:
        out_file = Path(output_path)
    else:
        out_file = Path("src/eval/results") / f"judge_eval_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"结果已保存到: {out_file}")

    return output


def load_cases_from_file(path: str) -> list:
    """从 JSON 文件加载评测用例。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 支持两种格式：直接是列表，或者 {cases: [...]}
    if isinstance(data, list):
        return data
    return data.get("cases", [])


def import_tau_bench_cases() -> list:
    """将 18 条 tau-bench-inspired 冒烟用例转换为 Judge 格式。"""
    from src.eval.tau_bench import E2E_CASES
    converted = []
    for i, case in enumerate(E2E_CASES):
        converted.append({
            "id": f"tau-{i+1:02d}",
            "query": case["query"],
            "category": case.get("category", "unknown"),
            "tags": case.get("platforms", ["bilibili"]),
            "source": "tau-bench-inspired",
        })
    return converted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-as-Judge 评测框架")
    parser.add_argument("--cases", type=str, help="用例 JSON 文件路径")
    parser.add_argument("--limit", type=int, help="只跑前 N 条")
    parser.add_argument("--output", type=str, help="输出 JSON 文件路径")
    parser.add_argument("--import-tau", action="store_true", help="导入 tau-bench 的 18 条用例")
    parser.add_argument("--all", action="store_true", help="跑内置 + tau-bench 全部用例")
    parser.add_argument("--judge-repeats", type=int, default=3, help="每份报告重复评分次数，默认 3")
    args = parser.parse_args()

    cases = None
    if args.cases:
        cases = load_cases_from_file(args.cases)
        print(f"从文件加载 {len(cases)} 条用例: {args.cases}")
    elif args.import_tau:
        cases = import_tau_bench_cases()
        print(f"导入 tau-bench {len(cases)} 条用例")
    elif args.all:
        cases = BUILTIN_CASES + import_tau_bench_cases()
        print(f"内置 {len(BUILTIN_CASES)} + tau-bench {len(import_tau_bench_cases())} = {len(cases)} 条用例")

    asyncio.run(run_eval(
        cases=cases,
        limit=args.limit,
        output_path=args.output,
        judge_repeats=args.judge_repeats,
    ))
