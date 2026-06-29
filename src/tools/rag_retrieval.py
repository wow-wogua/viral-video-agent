from src.rag.retriever import retrieve


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


async def rag_search(query: str, top_k: int = 5) -> list[str]:
    """从 RAG 知识库检索相关文档，自动过滤平台。"""
    try:
        platform = _detect_platform_from_query(query)
        return retrieve(query, top_k, platform=platform)
    except Exception as e:
        print(f"[rag] 检索失败: {e}")
        return []
