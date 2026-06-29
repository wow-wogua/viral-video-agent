import asyncio
import json
import sys
from src.agents.supervisor import get_llm, extract_text

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# BFCL 评测集：30 条，覆盖 search_videos / rag_search / get_transcript + 无需工具场景
TEST_CASES = [
    # ── search_videos 工具（15 条）──
    {
        "input": "搜索B站美妆类视频",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "美妆", "platforms": ["bilibili"]},
    },
    {
        "input": "搜索B站美食类视频TOP10",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "美食", "platforms": ["bilibili"], "limit": 10},
    },
    {
        "input": "帮我找B站最近的科技区热门视频",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "科技", "platforms": ["bilibili"]},
    },
    {
        "input": "看看最近有什么热门视频",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "", "platforms": ["bilibili"]},
    },
    {
        "input": "分析B站游戏区最近的爆款",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "游戏", "platforms": ["bilibili"]},
    },
    {
        "input": "找一下B站生活区点赞最高的视频",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "生活", "platforms": ["bilibili"]},
    },
    {
        "input": "获取B站热门排行榜前20名",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "", "platforms": ["bilibili"], "limit": 20},
    },
    {
        "input": "帮我找B站音乐区的热门MV",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "音乐", "platforms": ["bilibili"]},
    },
    {
        "input": "分析B站舞蹈区最近的爆款视频",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "舞蹈", "platforms": ["bilibili"]},
    },
    {
        "input": "看看B站知识区有什么热门内容",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "知识", "platforms": ["bilibili"]},
    },
    {
        "input": "找B站影视区最近的热门解说",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "影视", "platforms": ["bilibili"]},
    },
    {
        "input": "分析B站动画区的热门番剧",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "动画", "platforms": ["bilibili"]},
    },
    {
        "input": "看看B站汽车区有什么测评视频",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "汽车", "platforms": ["bilibili"]},
    },
    {
        "input": "找B站体育区最近的赛事集锦",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "体育", "platforms": ["bilibili"]},
    },
    {
        "input": "分析B站搞笑区的热门视频",
        "expected_tool": "search_videos",
        "expected_params": {"keyword": "搞笑", "platforms": ["bilibili"]},
    },

    # ── rag_search 工具（8 条）──
    {
        "input": "检索知识库中关于爆款公式的文档",
        "expected_tool": "rag_search",
        "expected_params": {"query": "爆款公式"},
    },
    {
        "input": "有没有历史爆款分析报告可以参考",
        "expected_tool": "rag_search",
        "expected_params": {"query": "爆款分析报告"},
    },
    {
        "input": "查一下抖音的算法规则",
        "expected_tool": "rag_search",
        "expected_params": {"query": "抖音算法规则"},
    },
    {
        "input": "知识库里有没有关于AIDA框架的内容",
        "expected_tool": "rag_search",
        "expected_params": {"query": "AIDA框架"},
    },
    {
        "input": "帮我找一下短视频运营的方法论",
        "expected_tool": "rag_search",
        "expected_params": {"query": "短视频运营方法论"},
    },
    {
        "input": "有没有关于竞品分析的文档",
        "expected_tool": "rag_search",
        "expected_params": {"query": "竞品分析"},
    },
    {
        "input": "检索一下2024年的行业趋势报告",
        "expected_tool": "rag_search",
        "expected_params": {"query": "2024年行业趋势"},
    },
    {
        "input": "知识库里有没有关于钩子设计的内容",
        "expected_tool": "rag_search",
        "expected_params": {"query": "钩子设计"},
    },

    # ── get_transcript 工具（3 条）──
    {
        "input": "把这个视频的文案转写出来",
        "expected_tool": "get_transcript",
        "expected_params": {"video_url": "..."},
    },
    {
        "input": "获取这个视频的字幕内容",
        "expected_tool": "get_transcript",
        "expected_params": {"video_url": "..."},
    },
    {
        "input": "帮我转写一下这个视频的口播文案",
        "expected_tool": "get_transcript",
        "expected_params": {"video_url": "..."},
    },

    # ── 不需要工具的场景（4 条）──
    {
        "input": "帮我总结一下分析结果",
        "expected_tool": None,  # 不应调用工具
        "expected_params": {},
    },
    {
        "input": "根据已有数据，给出运营建议",
        "expected_tool": None,
        "expected_params": {},
    },
    {
        "input": "解释一下什么是爆款视频",
        "expected_tool": None,
        "expected_params": {},
    },
    {
        "input": "帮我写一个短视频脚本大纲",
        "expected_tool": None,
        "expected_params": {},
    },
]


async def eval_tool_accuracy():
    """评估工具调用准确率（BFCL 范式）。"""
    llm = get_llm()
    correct = 0
    total = len(TEST_CASES)
    results = []

    for i, case in enumerate(TEST_CASES):
        if i > 0:
            await asyncio.sleep(1)  # 避免 API 限流
        prompt = f"""你是研究员。请根据任务描述，输出要调用的工具和参数。

任务: {case['input']}

可用工具:
- search_videos(keyword, platforms, limit): Get trending videos from Bilibili ranking.
- get_transcript(video_url): Get video transcript.
- rag_search(query, top_k): Search knowledge base for reference documents.
- 无需工具: 如果任务不需要调用任何工具，输出 {{"tool": null, "params": {{}}}}

输出 JSON: {{"tool": "工具名", "params": {{"参数名": "值"}}}}"""

        for retry in range(3):
            try:
                response = await llm.ainvoke([{"role": "user", "content": prompt}])
                break
            except Exception as e:
                if "429" in str(e) and retry < 2:
                    wait = (retry + 1) * 5
                    print(f"  [RETRY] 限流，等待 {wait}s 后重试...")
                    await asyncio.sleep(wait)
                else:
                    raise
        text = extract_text(response)

        try:
            text_clean = text.strip()
            if text_clean.startswith("```"):
                text_clean = text_clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(text_clean)

            actual_tool = result.get("tool")
            expected_tool = case["expected_tool"]

            # 匹配逻辑：expected_tool 为 None 时，actual_tool 也应为 None
            if expected_tool is None:
                is_correct = actual_tool is None
            else:
                is_correct = actual_tool == expected_tool

            if is_correct:
                correct += 1
                status = "✅"
            else:
                status = "❌"

            print(f"  {status} [{i+1:02d}] {case['input']} → 期望={expected_tool}, 实际={actual_tool}")
            results.append({
                "case": i + 1,
                "input": case["input"],
                "expected": expected_tool,
                "actual": actual_tool,
                "correct": is_correct,
            })

        except (json.JSONDecodeError, AttributeError) as e:
            print(f"  ❌ [{i+1:02d}] {case['input']} → JSON 解析失败: {e}")
            results.append({
                "case": i + 1,
                "input": case["input"],
                "expected": case["expected_tool"],
                "actual": "parse_error",
                "correct": False,
            })

    accuracy = correct / total * 100
    print(f"\n{'='*50}")
    print(f"工具调用准确率: {correct}/{total} ({accuracy:.1f}%)")
    print(f"{'='*50}")

    # 输出 JSON 结果便于后续分析
    summary = {
        "correct": correct,
        "total": total,
        "accuracy": accuracy,
        "details": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    asyncio.run(eval_tool_accuracy())
