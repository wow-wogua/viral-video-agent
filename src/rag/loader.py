import os
from pathlib import Path

# 平台关键词映射
_PLATFORM_KEYWORDS = {
    "bilibili": ["B站", "bilibili", "哔哩哔哩", "B站推荐"],
    "douyin": ["抖音", "抖店", "巨量"],
    "kuaishou": ["快手", "磁力金牛"],
}

# 通用内容（不包含平台特定信息，任何平台都适用）
_GENERIC_CATEGORIES = ["industry_methodology", "competitor_analysis", "trend_data"]


def _detect_platform(file_path: Path, content: str) -> str:
    """检测文档所属平台。"""
    path_str = str(file_path).lower()

    # 按路径判断
    if "platform_rules" in path_str:
        for platform, keywords in _PLATFORM_KEYWORDS.items():
            if any(kw in path_str for kw in keywords):
                return platform

    # 按内容判断（仅对 platform_rules 目录下的文件做精确判断）
    for platform, keywords in _PLATFORM_KEYWORDS.items():
        if any(kw in content[:500] for kw in keywords):
            # 如果是行业方法论类文档，但内容提到了特定平台，标记为该平台
            if "platform_rules" in path_str:
                return platform

    # 通用内容
    return "generic"


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
            platform = _detect_platform(file_path, content)
            docs.append({
                "content": content,
                "source": str(file_path),
                "platform": platform,
            })

    print(f"[loader] 加载了 {len(docs)} 个文档")
    return docs
