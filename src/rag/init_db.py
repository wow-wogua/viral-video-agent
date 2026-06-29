"""
初始化知识库：加载文档 → 切片 → 导入 ChromaDB。
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.rag.loader import load_documents
from src.rag.splitter import split_documents
from src.rag.embedder import get_or_create_collection


def init_knowledge_base():
    """初始化知识库。"""
    print("=== 初始化知识库 ===\n")

    # 1. 加载文档
    docs = load_documents("knowledge")
    if not docs:
        print("没有找到文档，退出")
        return

    # 2. 切片
    chunks = split_documents(docs, chunk_size=1000, chunk_overlap=200)
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
            metadatas=[{"source": c["source"], "platform": c.get("platform", "generic")} for c in batch],
            ids=[f"chunk-{i+j}" for j in range(len(batch))],
        )
        print(f"  导入 {i+len(batch)}/{len(chunks)}")

    print(f"\n✅ 完成，共导入 {collection.count()} 条文档")


if __name__ == "__main__":
    init_knowledge_base()
