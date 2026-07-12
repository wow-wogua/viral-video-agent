"""Architecture v2 当前能力范围内的工具路由评测。"""

import argparse
import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage

from src.agents.supervisor import extract_text, get_llm
from src.graph.v2 import _parse_json_object, entry_node
from src.prompts.manager import prompt_manager
from src.tools.capabilities import normalize_tool_params, render_available_tools


DEV_CASES = [
    # 当前真实视频搜索：只测 bilibili。
    {"input": "搜索B站美妆类热门视频", "platforms": ["bilibili"], "tool": "search_videos", "params": {"keyword": "美妆", "platforms": ["bilibili"]}},
    {"input": "找B站最近的科技区爆款", "platforms": ["bilibili"], "tool": "search_videos", "params": {"keyword": "科技", "platforms": ["bilibili"]}},
    {"input": "获取B站热门排行榜前20名", "platforms": ["bilibili"], "tool": "search_videos", "params": {"keyword": "", "platforms": ["bilibili"], "limit": 20}},
    {"input": "分析B站游戏区最近的热门视频样本", "platforms": ["bilibili"], "tool": "search_videos", "params": {"keyword": "游戏", "platforms": ["bilibili"]}},
    {"input": "帮我找B站音乐区近期热视频", "platforms": ["bilibili"], "tool": "search_videos", "params": {"keyword": "音乐", "platforms": ["bilibili"]}},
    {"input": "拉10条B站知识区热门视频", "platforms": ["bilibili"], "tool": "search_videos", "params": {"keyword": "知识", "platforms": ["bilibili"], "limit": 10}},
    {"input": "找B站汽车区最近的测评视频", "platforms": ["bilibili"], "tool": "search_videos", "params": {"keyword": "汽车", "platforms": ["bilibili"]}},
    {"input": "B站生活区最近有什么火的视频", "platforms": ["bilibili"], "tool": "search_videos", "params": {"keyword": "生活", "platforms": ["bilibili"]}},
    # 本地知识库。
    {"input": "检索知识库中关于爆款公式的资料", "platforms": ["bilibili"], "tool": "rag_search", "params": {"query": "爆款公式"}},
    {"input": "查一下B站推荐算法规则", "platforms": ["bilibili"], "tool": "rag_search", "params": {"query": "B站推荐算法规则"}},
    {"input": "知识库有没有AIDA框架", "platforms": ["bilibili"], "tool": "rag_search", "params": {"query": "AIDA框架"}},
    {"input": "找一份竞品分析方法论", "platforms": ["bilibili"], "tool": "rag_search", "params": {"query": "竞品分析方法论"}},
    {"input": "检索短视频开头钩子设计资料", "platforms": ["bilibili"], "tool": "rag_search", "params": {"query": "短视频开头钩子设计"}},
    {"input": "查知识库里的完播率指标定义", "platforms": ["bilibili"], "tool": "rag_search", "params": {"query": "完播率指标定义"}},
    {"input": "有没有历史爆款分析报告可参考", "platforms": ["bilibili"], "tool": "rag_search", "params": {"query": "历史爆款分析报告"}},
    {"input": "查一下抖音算法规则资料，不需要实时视频", "platforms": ["douyin"], "tool": "rag_search", "params": {"query": "抖音算法规则"}},
    # 无需新增证据。
    {"input": "根据已有数据总结三个发现", "platforms": ["bilibili"], "tool": None, "params": {}},
    {"input": "不要调用工具，直接解释什么是完播率", "platforms": ["bilibili"], "tool": None, "params": {}},
    {"input": "把已有报告改得更简洁", "platforms": ["bilibili"], "tool": None, "params": {}},
    {"input": "直接写三个标题，不用查资料", "platforms": ["bilibili"], "tool": None, "params": {}},
    # 不支持的实时平台能力，走入口确定性边界。
    {"input": "搜索抖音最近的热门视频样本", "platforms": ["douyin"], "entry_status": "unsupported_platform"},
    {"input": "找快手当前爆款排行榜", "platforms": ["kuaishou"], "entry_status": "unsupported_platform"},
    {"input": "拉一批小红书近期热门美妆视频", "platforms": ["xiaohongshu"], "entry_status": "unsupported_platform"},
]

HOLDOUT_CASES = [
    {"input": "给我拿几条B站数码区近期热视频", "platforms": ["bilibili"], "tool": "search_videos", "params": {"keyword": "数码", "platforms": ["bilibili"]}},
    {"input": "B站体育区当前热门找15个", "platforms": ["bilibili"], "tool": "search_videos", "params": {"keyword": "体育", "platforms": ["bilibili"], "limit": 15}},
    {"input": "想复盘B站动画区爆款，先拉真实样本", "platforms": ["bilibili"], "tool": "search_videos", "params": {"keyword": "动画", "platforms": ["bilibili"]}},
    {"input": "B站美食最近火什么，先找视频", "platforms": ["bilibili"], "tool": "search_videos", "params": {"keyword": "美食", "platforms": ["bilibili"]}},
    {"input": "找知识库里的标题写作框架", "platforms": ["bilibili"], "tool": "rag_search", "params": {"query": "标题写作框架"}},
    {"input": "参考一下账号定位方法论", "platforms": ["bilibili"], "tool": "rag_search", "params": {"query": "账号定位方法论"}},
    {"input": "查B站流量分发规则的资料", "platforms": ["bilibili"], "tool": "rag_search", "params": {"query": "B站流量分发规则"}},
    {"input": "有没有短视频竞品复盘模板", "platforms": ["bilibili"], "tool": "rag_search", "params": {"query": "短视频竞品复盘模板"}},
    {"input": "基于上面的样本直接写结论", "platforms": ["bilibili"], "tool": None, "params": {}},
    {"input": "不用检索，改写这段分析报告", "platforms": ["bilibili"], "tool": None, "params": {}},
    {"input": "直接解释互动率，不需要查资料", "platforms": ["bilibili"], "tool": None, "params": {}},
    {"input": "搜快手最近的游戏热视频", "platforms": ["kuaishou"], "entry_status": "unsupported_platform"},
    {"input": "拉一批小红书近期家居爆款样本", "platforms": ["xiaohongshu"], "entry_status": "unsupported_platform"},
]


def _normalize_text(value: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:；;\-_/]+", "", value or "").lower()


def _semantic_value(key: str, value):
    if isinstance(value, list):
        return sorted(value)
    if not isinstance(value, str):
        return value
    normalized = _normalize_text(value)
    if key == "keyword":
        for fragment in ("b站", "bilibili", "最近", "近期", "当前", "热门", "爆款", "视频", "区", "样本"):
            normalized = normalized.replace(fragment, "")
    if key == "query":
        for fragment in ("有没有", "查一下", "检索", "找一份", "资料", "内容", "的", "可参考"):
            normalized = normalized.replace(fragment, "")
    return normalized


def params_match(actual: dict, expected: dict) -> bool:
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        actual_normalized = _semantic_value(key, actual_value)
        expected_normalized = _semantic_value(key, expected_value)
        if key in {"keyword", "query"} and isinstance(actual_normalized, str):
            if not (
                actual_normalized == expected_normalized
                or actual_normalized in expected_normalized
                or expected_normalized in actual_normalized
            ):
                return False
        elif actual_normalized != expected_normalized:
            return False
    return True


async def evaluate_case(index: int, case: dict) -> dict:
    if case.get("entry_status"):
        result = await entry_node({"user_request": case["input"], "platforms": case["platforms"]})
        actual_status = result.get("termination_reason", "")
        return {
            "case": index,
            "input": case["input"],
            "kind": "entry_boundary",
            "expected": case["entry_status"],
            "actual": actual_status,
            "tool_correct": actual_status == case["entry_status"],
            "params_correct": actual_status == case["entry_status"],
            "fully_correct": actual_status == case["entry_status"],
        }

    prompt = prompt_manager.get(
        "researcher_dynamic",
        task=case["input"],
        platforms=case["platforms"],
        available_tools=render_available_tools(),
    )
    started = time.perf_counter()
    response = await get_llm("researcher").ainvoke([HumanMessage(content=prompt)])
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    parsed = _parse_json_object(extract_text(response))
    actual_tool = parsed.get("tool")
    if actual_tool in (None, "none"):
        actual_tool = None
        actual_params = {}
    else:
        try:
            actual_params = normalize_tool_params(actual_tool, parsed.get("params", {}))
        except (ValueError, TypeError) as exc:
            actual_params = parsed.get("params", {}) if isinstance(parsed.get("params"), dict) else {}
            return {
                "case": index,
                "input": case["input"],
                "kind": "tool_routing",
                "expected_tool": case["tool"],
                "actual_tool": actual_tool,
                "actual_params": actual_params,
                "tool_correct": actual_tool == case["tool"],
                "params_correct": False,
                "fully_correct": False,
                "latency_ms": latency_ms,
                "validation_error": str(exc),
            }
    tool_correct = actual_tool == case["tool"]
    param_correct = tool_correct and params_match(actual_params, case["params"])
    return {
        "case": index,
        "input": case["input"],
        "kind": "tool_routing",
        "expected_tool": case["tool"],
        "actual_tool": actual_tool,
        "actual_params": actual_params,
        "tool_correct": tool_correct,
        "params_correct": param_correct,
        "fully_correct": tool_correct and param_correct,
        "latency_ms": latency_ms,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.split == "dev":
        cases = DEV_CASES
    elif args.split == "holdout":
        cases = HOLDOUT_CASES
    else:
        cases = DEV_CASES + HOLDOUT_CASES
    cases = cases[:args.limit] if args.limit else cases
    results = []
    for index, case in enumerate(cases, start=1):
        if index > 1:
            await asyncio.sleep(0.5)
        result = await evaluate_case(index, case)
        results.append(result)
        print(f"[{index:02d}] {'PASS' if result['fully_correct'] else 'FAIL'} {case['input']}")

    total = len(results)
    tool_correct = sum(item["tool_correct"] for item in results)
    params_correct = sum(item["params_correct"] for item in results)
    full_correct = sum(item["fully_correct"] for item in results)
    payload = {
        "timestamp": datetime.now().isoformat(),
        "scope": "runtime-enabled capabilities only",
        "split": args.split,
        "total": total,
        "tool_correct": tool_correct,
        "params_correct": params_correct,
        "full_correct": full_correct,
        "tool_accuracy": tool_correct / total * 100 if total else 0.0,
        "params_accuracy": params_correct / total * 100 if total else 0.0,
        "full_accuracy": full_correct / total * 100 if total else 0.0,
        "details": results,
    }
    output = Path(args.output) if args.output else Path(
        f"src/eval/results/capability_routing_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "details"}, ensure_ascii=False, indent=2))
    print(f"结果已保存: {output}")


if __name__ == "__main__":
    asyncio.run(main())
