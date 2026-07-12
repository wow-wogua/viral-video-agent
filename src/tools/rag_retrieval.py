from src.rag.retriever import retrieve_with_metadata


def _detect_platform_from_query(query: str) -> str | None:
    """从查询文本中检测目标平台。"""
    q = query.lower()
    if "b站" in q or "bilibili" in q or "哔哩哔哩" in q:
        return "bilibili"
    if "抖音" in q or "抖店" in q or "巨量" in q:
        return "douyin"
    if "快手" in q or "磁力金牛" in q:
        return "kuaishou"
    return None


async def rag_search(query: str, top_k: int = 5, platform: str | None = None) -> list[dict]:
    """检索知识库并返回可追溯的正文、文档、章节与来源 URL。"""
    try:
        platform = platform or _detect_platform_from_query(query)
        results = retrieve_with_metadata(query, top_k, platform=platform)
        return [
            {
                "content": item["content"],
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "source_url": item.get("source_url", ""),
                "source_urls": item.get("source_urls", []),
                "category": item.get("category", ""),
                "platform": item.get("platform", "generic"),
                "heading_path": item.get("heading_path", ""),
                "source_tier": item.get("source_tier", "internal"),
            }
            for item in results
        ]
    except Exception as e:
        print(f"[rag] 检索失败: {e}")
        return []
