from src.rag.embedder import get_or_create_collection


def retrieve(query: str, top_k: int = 5) -> list[str]:
    """从 ChromaDB 检索相关文档。"""
    collection = get_or_create_collection("knowledge")

    results = collection.query(
        query_texts=[query],
        n_results=top_k,
    )

    documents = results.get("documents", [[]])[0]
    print(f"[retriever] 检索到 {len(documents)} 条结果")
    return documents
