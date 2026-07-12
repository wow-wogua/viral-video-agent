"""
初始化知识库：加载文档 → 切片 → 导入 ChromaDB。
"""
import json
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.rag.loader import load_documents
from src.rag.splitter import split_documents
from src.rag.embedder import get_or_create_collection


def _chroma_metadata(chunk: dict) -> dict:
    """Chroma metadata 仅支持标量；保留检索和溯源需要的字段。"""
    return {
        "doc_id": chunk["doc_id"],
        "title": chunk["title"],
        "source": chunk["source"],
        "category": chunk["category"],
        "platform": chunk.get("platform", "generic"),
        "content_type": chunk["content_type"],
        "published_at": chunk["published_at"],
        "collected_at": chunk["collected_at"],
        "source_url": chunk.get("source_urls", [""])[0] if chunk.get("source_urls") else "",
        "source_urls_json": json.dumps(chunk.get("source_urls", []), ensure_ascii=False),
        "source_count": chunk.get("source_count", 0),
        "source_tier": chunk.get("source_tier", "internal"),
        "provenance_status": chunk.get("provenance_status", "missing"),
        "heading_path": chunk["heading_path"],
        "chunk_index": chunk["chunk_index"],
        "chunk_hash": chunk["chunk_hash"],
    }


def init_knowledge_base():
    """初始化知识库。"""
    print("=== 初始化知识库 ===\n")

    # 1. 加载文档
    docs = load_documents("knowledge")
    if not docs:
        print("没有找到文档，退出")
        return

    # 2. 切片
    chunks = split_documents(docs, chunk_size=1000, chunk_overlap=150)
    if not chunks:
        print("切片为空，退出")
        return

    # 3. 导入 ChromaDB
    collection = get_or_create_collection("knowledge")

    # 清空旧数据
    if collection.count() > 0:
        print(f"清空旧数据 ({collection.count()} 条)")
        # 获取所有 ID 然后删除（ChromaDB 不支持 where={})
        all_data = collection.get()
        if all_data["ids"]:
            collection.delete(ids=all_data["ids"])

    # 批量导入
    batch_size = 100
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        collection.add(
            documents=[c["content"] for c in batch],
            metadatas=[_chroma_metadata(c) for c in batch],
            ids=[c["chunk_id"] for c in batch],
        )
        print(f"  导入 {i+len(batch)}/{len(chunks)}")

    print(f"\n✅ 完成，共导入 {collection.count()} 条文档")


if __name__ == "__main__":
    init_knowledge_base()
