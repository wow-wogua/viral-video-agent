import os
from pathlib import Path


def load_documents(knowledge_dir: str = "knowledge") -> list[dict]:
    """加载 knowledge/ 目录下的所有文档。"""
    docs = []
    knowledge_path = Path(knowledge_dir)

    if not knowledge_path.exists():
        print(f"[loader] 目录不存在: {knowledge_dir}")
        return docs

    for file_path in knowledge_path.rglob("*"):
        if file_path.is_file() and file_path.suffix in (".md", ".txt"):
            content = file_path.read_text(encoding="utf-8")
            docs.append({
                "content": content,
                "source": str(file_path),
            })

    print(f"[loader] 加载了 {len(docs)} 个文档")
    return docs
