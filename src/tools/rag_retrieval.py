from src.rag.retriever import retrieve


async def rag_search(query: str, top_k: int = 5) -> list[str]:
    """从 RAG 知识库检索相关文档。"""
    try:
        return retrieve(query, top_k)
    except Exception as e:
        print(f"[rag] 检索失败: {e}")
        return []
