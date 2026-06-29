def split_documents(docs: list[dict], chunk_size: int = 1000, chunk_overlap: int = 200) -> list[dict]:
    """将文档切片。"""
    chunks = []

    for doc in docs:
        content = doc["content"]
        source = doc["source"]
        platform = doc.get("platform", "generic")

        start = 0
        while start < len(content):
            end = start + chunk_size
            chunk_text = content[start:end]

            if chunk_text.strip():
                chunks.append({
                    "content": chunk_text,
                    "source": source,
                    "platform": platform,
                })

            start += chunk_size - chunk_overlap

    print(f"[splitter] 切分为 {len(chunks)} 个片段")
    return chunks
