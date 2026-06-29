from src.rag.embedder import get_or_create_collection


def retrieve(query: str, top_k: int = 5, platform: str = None) -> list[str]:
    """从 ChromaDB 检索相关文档。

    Args:
        query: 检索查询
        top_k: 返回数量
        platform: 平台过滤（bilibili/douyin/kuaishou），None 表示不过滤
    """
    collection = get_or_create_collection("knowledge")

    # 构建过滤条件：只返回目标平台 + 通用内容
    where = None
    if platform:
        where = {"platform": {"$in": [platform, "generic"]}}

    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where,
    )

    documents = results.get("documents", [[]])[0]
    print(f"[retriever] 检索到 {len(documents)} 条结果 (platform={platform})")
    return documents
