import asyncio
import json
import os
import sys
import tarfile
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── 模型下载 ──
CACHE_DIR = Path.home() / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2"
MODEL_FILE = CACHE_DIR / "onnx.tar.gz"
MODEL_URL = "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"


def ensure_model():
    """确保 embedding 模型已下载并解压。"""
    onnx_dir = CACHE_DIR / "onnx"

    # 已解压，直接返回
    if onnx_dir.exists() and any(onnx_dir.iterdir()):
        print(f"[模型] 已存在，跳过下载")
        return True

    # 压缩包已下载，只解压
    if MODEL_FILE.exists() and MODEL_FILE.stat().st_size > 1_000_000:
        print(f"[模型] 压缩包已存在，解压中...")
        with tarfile.open(MODEL_FILE, "r:gz") as tar:
            tar.extractall(path=CACHE_DIR)
        print("[模型] 解压完成")
        return True

    # 需要下载
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[模型] 下载中: {MODEL_URL}")
    print("[模型] 首次下载约 80MB，可能需要几分钟...")
    try:
        with httpx.Client(timeout=600, follow_redirects=True) as client:
            resp = client.get(MODEL_URL)
            resp.raise_for_status()
            with open(MODEL_FILE, "wb") as f:
                f.write(resp.content)
        print(f"[模型] 下载完成: {MODEL_FILE.stat().st_size / 1024 / 1024:.1f} MB")
    except Exception as e:
        print(f"[模型] 下载失败: {e}")
        print(f"[模型] 请手动下载: {MODEL_URL}")
        print(f"[模型] 放到: {CACHE_DIR}")
        return False

    # 解压
    print("[模型] 解压中...")
    with tarfile.open(MODEL_FILE, "r:gz") as tar:
        tar.extractall(path=CACHE_DIR)
    print("[模型] 解压完成")
    return True


# ── 以下为原有代码 ──
from src.graph.builder import build_graph
from src.rag.retriever import retrieve


# RAG 检索测试集：28 条，覆盖 5 个知识库分类(platform_rules/industry_methodology/trend_data/historical_reports/competitor_analysis) + 跨分类
RAG_TEST_CASES = [
    # platform_rules (5 条)
    {"query": "抖音的推荐算法是什么原理", "relevant_docs": ["抖音"], "category": "platform_rules"},
    {"query": "B站的流量分配机制", "relevant_docs": ["B站", "bilibili"], "category": "platform_rules"},
    {"query": "小红书的内容审核规则", "relevant_docs": ["小红书"], "category": "platform_rules"},
    {"query": "快手的算法推荐逻辑", "relevant_docs": ["快手"], "category": "platform_rules"},
    {"query": "各平台的违规内容标准是什么", "relevant_docs": ["违规", "审核"], "category": "platform_rules"},

    # industry_methodology (6 条)
    {"query": "爆款视频的开头怎么写", "relevant_docs": ["钩子", "hook", "AIDA"], "category": "industry_methodology"},
    {"query": "AIDA框架怎么用在短视频里", "relevant_docs": ["AIDA"], "category": "industry_methodology"},
    {"query": "短视频的爆款公式是什么", "relevant_docs": ["爆款公式", "公式"], "category": "industry_methodology"},
    {"query": "短视频脚本怎么写", "relevant_docs": ["脚本", "结构"], "category": "industry_methodology"},
    {"query": "怎么设计短视频的封面", "relevant_docs": ["封面"], "category": "industry_methodology"},
    {"query": "短视频选题有什么方法", "relevant_docs": ["选题"], "category": "industry_methodology"},

    # trend_data (5 条)
    {"query": "2024年美妆行业趋势", "relevant_docs": ["美妆", "趋势"], "category": "trend_data"},
    {"query": "最近短视频平台的热点话题", "relevant_docs": ["热点", "话题"], "category": "trend_data"},
    {"query": "2025年短视频行业发展方向", "relevant_docs": ["趋势", "发展"], "category": "trend_data"},
    {"query": "3C电子行业的短视频趋势", "relevant_docs": ["3C", "电子"], "category": "trend_data"},
    {"query": "美食行业的短视频数据表现", "relevant_docs": ["美食", "数据"], "category": "trend_data"},

    # historical_reports (5 条)
    {"query": "有没有美妆垂直领域的分析报告", "relevant_docs": ["美妆", "垂直"], "category": "historical_reports"},
    {"query": "历史爆款分析报告里有什么规律", "relevant_docs": ["报告", "规律"], "category": "historical_reports"},
    {"query": "有没有直播带货的分析报告", "relevant_docs": ["直播", "带货"], "category": "historical_reports"},
    {"query": "过去一年的爆款视频有什么共同特征", "relevant_docs": ["爆款", "特征"], "category": "historical_reports"},
    {"query": "有没有食品行业的短视频分析", "relevant_docs": ["食品"], "category": "historical_reports"},

    # competitor_analysis (4 条)
    {"query": "竞品是怎么做短视频的", "relevant_docs": ["竞品"], "category": "competitor_analysis"},
    {"query": "同类账号的爆款视频有什么特征", "relevant_docs": ["账号", "特征"], "category": "competitor_analysis"},
    {"query": "怎么分析竞品账号的内容策略", "relevant_docs": ["竞品", "策略"], "category": "competitor_analysis"},
    {"query": "竞品分析有哪些维度", "relevant_docs": ["竞品", "维度"], "category": "competitor_analysis"},

    # 跨分类检索 (3 条)
    {"query": "如何提高短视频的完播率", "relevant_docs": ["完播率", "数据"], "category": "cross"},
    {"query": "短视频选题有什么技巧", "relevant_docs": ["选题"], "category": "cross"},
    {"query": "怎么写短视频标题吸引人", "relevant_docs": ["标题", "钩子"], "category": "cross"},
]


def eval_rag_retrieval():
    """评测 RAG 检索质量。"""
    # 确保模型已下载
    if not ensure_model():
        print("模型下载失败，退出")
        return

    print("\nRAG 检索质量评测")
    print(f"{'='*60}")

    total = len(RAG_TEST_CASES)
    hit_count = 0
    results = []

    for i, case in enumerate(RAG_TEST_CASES):
        docs = retrieve(case["query"], top_k=5)
        doc_text = " ".join(docs).lower()

        # 检查是否命中相关文档
        hit = any(keyword.lower() in doc_text for keyword in case["relevant_docs"])
        if hit:
            hit_count += 1
            status = "✅"
        else:
            status = "❌"

        print(f"  {status} [{i+1:02d}] {case['query']} | 检索到 {len(docs)} 条 | 命中={hit}")
        results.append({
            "case": i + 1,
            "query": case["query"],
            "category": case["category"],
            "hit": hit,
            "retrieved_count": len(docs),
        })

    hit_rate = hit_count / total * 100
    print(f"\n{'='*60}")
    print(f"检索命中率: {hit_count}/{total} ({hit_rate:.1f}%)")
    print(f"{'='*60}")

    # 按分类统计
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "hit": 0}
        categories[cat]["total"] += 1
        if r["hit"]:
            categories[cat]["hit"] += 1

    print("\n分类统计:")
    for cat, stats in categories.items():
        rate = stats["hit"] / stats["total"] * 100
        print(f"  {cat}: {stats['hit']}/{stats['total']} ({rate:.1f}%)")

    summary = {
        "total": total,
        "hit": hit_count,
        "hit_rate": hit_rate,
        "by_category": {cat: {"hit": s["hit"], "total": s["total"], "rate": round(s["hit"]/s["total"]*100, 1)} for cat, s in categories.items()},
        "details": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


async def ablation_test():
    """消融实验：有 RAG vs 无 RAG 的报告质量对比。"""
    graph = build_graph()

    # 测试查询
    test_queries = [
        "分析B站美妆区热门视频的爆款规律",
        "分析B站科技区视频的内容特征",
    ]

    results = []
    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"查询: {query}")

        # 有 RAG
        print("\n[有 RAG] 运行中...")
        start = time.time()
        result_rag = await graph.ainvoke(
            {
                "user_request": query,
                "task_complete": False,
                "data_sufficient": False,
                "analysis_confidence": 0.0,
                "report_final": "",
            },
            config={"configurable": {"thread_id": "ablation-rag"}, "recursion_limit": 50},
        )
        rag_latency = time.time() - start
        rag_report = result_rag.get("report_final", "")

        # 无 RAG（模拟：不调用 rag_search）
        print("[无 RAG] 运行中...")
        start = time.time()
        result_no_rag = await graph.ainvoke(
            {
                "user_request": query,
                "task_complete": False,
                "data_sufficient": False,
                "analysis_confidence": 0.0,
                "report_final": "",
                "rag_context": [],  # 清空 RAG 上下文
            },
            config={"configurable": {"thread_id": "ablation-no-rag"}, "recursion_limit": 50},
        )
        no_rag_latency = time.time() - start
        no_rag_report = result_no_rag.get("report_final", "")

        entry = {
            "query": query,
            "rag_report_length": len(rag_report),
            "no_rag_report_length": len(no_rag_report),
            "rag_latency_s": round(rag_latency, 1),
            "no_rag_latency_s": round(no_rag_latency, 1),
            "rag_has_data_ref": any(kw in rag_report for kw in ["数据", "统计", "比例", "%"]),
            "no_rag_has_data_ref": any(kw in no_rag_report for kw in ["数据", "统计", "比例", "%"]),
            "rag_has_methodology": any(kw in rag_report for kw in ["AIDA", "框架", "方法论", "公式"]),
            "no_rag_has_methodology": any(kw in no_rag_report for kw in ["AIDA", "框架", "方法论", "公式"]),
        }
        results.append(entry)

        print(f"\n  有 RAG: {entry['rag_report_length']} 字 | {entry['rag_latency_s']}s | 数据引用={entry['rag_has_data_ref']} | 方法论={entry['rag_has_methodology']}")
        print(f"  无 RAG: {entry['no_rag_report_length']} 字 | {entry['no_rag_latency_s']}s | 数据引用={entry['no_rag_has_data_ref']} | 方法论={entry['no_rag_has_methodology']}")

    print(f"\n{'='*60}")
    print("消融实验结果")
    print(f"{'='*60}")
    for r in results:
        print(f"\n查询: {r['query']}")
        print(f"  有 RAG: {r['rag_report_length']} 字, 数据引用={r['rag_has_data_ref']}, 方法论引用={r['rag_has_methodology']}")
        print(f"  无 RAG: {r['no_rag_report_length']} 字, 数据引用={r['no_rag_has_data_ref']}, 方法论引用={r['no_rag_has_methodology']}")

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["retrieval", "ablation"], default="retrieval")
    args = parser.parse_args()

    if args.mode == "retrieval":
        eval_rag_retrieval()
    else:
        asyncio.run(ablation_test())
