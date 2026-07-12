import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


_PLATFORM_KEYWORDS = {
    "bilibili": ["b站", "bilibili", "哔哩哔哩"],
    "douyin": ["抖音", "抖店", "巨量"],
    "kuaishou": ["快手", "磁力金牛"],
    "xiaohongshu": ["小红书", "xiaohongshu"],
}

_CONTENT_TYPES = {
    "platform_rules": "platform_policy",
    "industry_methodology": "methodology",
    "trend_data": "trend_summary",
    "historical_reports": "case_summary",
    "competitor_analysis": "analysis_framework",
}

_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")
_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """解析可选 YAML frontmatter；格式错误时明确失败，避免静默丢元数据。"""
    if not content.startswith("---\n"):
        return {}, content

    closing = content.find("\n---\n", 4)
    if closing == -1:
        raise ValueError("YAML frontmatter 缺少结束标记")

    raw_metadata = yaml.safe_load(content[4:closing]) or {}
    if not isinstance(raw_metadata, dict):
        raise ValueError("YAML frontmatter 必须是对象")
    return raw_metadata, content[closing + 5:].lstrip()


def _normalize_text(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip()


def _content_hash(content: str) -> str:
    return hashlib.sha256(_normalize_text(content).encode("utf-8")).hexdigest()


def _detect_platform(file_path: Path, content: str, configured: str | None = None) -> str:
    if configured:
        return str(configured).lower()

    filename = file_path.stem.lower()
    filename_matches = [
        platform
        for platform, keywords in _PLATFORM_KEYWORDS.items()
        if any(keyword in filename for keyword in keywords)
    ]
    if len(filename_matches) == 1:
        return filename_matches[0]

    if file_path.parent.name == "platform_rules":
        title_match = _HEADING_RE.search(content)
        title = title_match.group(1).lower() if title_match else ""
        title_matches = [
            platform
            for platform, keywords in _PLATFORM_KEYWORDS.items()
            if any(keyword in title for keyword in keywords)
        ]
        if len(title_matches) == 1:
            return title_matches[0]
    return "generic"


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item]
    raise ValueError("source_urls 必须是字符串或字符串列表")


def _document_metadata(file_path: Path, knowledge_path: Path, content: str, configured: dict) -> dict:
    relative_source = file_path.relative_to(knowledge_path.parent).as_posix()
    category = str(configured.get("category") or file_path.parent.name)
    title_match = _HEADING_RE.search(content)
    title = str(configured.get("title") or (title_match.group(1).strip() if title_match else file_path.stem))
    source_urls = _as_string_list(configured.get("source_urls"))
    source_urls.extend(_MARKDOWN_LINK_RE.findall(content))
    source_urls = list(dict.fromkeys(source_urls))
    source_tier = str(configured.get("source_tier") or ("secondary" if source_urls else "internal"))

    published_at = configured.get("published_at")
    if published_at is None:
        year_match = _YEAR_RE.search(title)
        published_at = year_match.group(1) if year_match else "unknown"

    return {
        "doc_id": hashlib.sha1(relative_source.encode("utf-8")).hexdigest()[:16],
        "title": title,
        "source": relative_source,
        "category": category,
        "platform": _detect_platform(file_path, content, configured.get("platform")),
        "content_type": str(configured.get("content_type") or _CONTENT_TYPES.get(category, "reference")),
        "published_at": str(published_at),
        "collected_at": str(
            configured.get("collected_at")
            or datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).date().isoformat()
        ),
        "source_urls": source_urls,
        "source_count": len(source_urls),
        "source_tier": source_tier,
        "provenance_status": "sourced" if source_urls else "missing",
        "content_hash": _content_hash(content),
    }


def load_documents(knowledge_dir: str = "knowledge") -> list[dict]:
    """加载、规范化并按正文哈希去重 knowledge/ 下的 Markdown/TXT 文档。"""
    knowledge_path = Path(knowledge_dir)
    if not knowledge_path.exists():
        print(f"[loader] 目录不存在: {knowledge_dir}")
        return []

    docs: list[dict] = []
    seen_hashes: dict[str, str] = {}
    for file_path in sorted(knowledge_path.rglob("*")):
        if not file_path.is_file() or file_path.suffix.lower() not in (".md", ".txt"):
            continue

        raw_content = file_path.read_text(encoding="utf-8")
        configured, content = _parse_frontmatter(raw_content)
        if not content.strip():
            print(f"[loader] 跳过空文档: {file_path}")
            continue

        metadata = _document_metadata(file_path, knowledge_path, content, configured)
        duplicate_of = seen_hashes.get(metadata["content_hash"])
        if duplicate_of:
            print(f"[loader] 跳过重复文档: {metadata['source']} == {duplicate_of}")
            continue
        seen_hashes[metadata["content_hash"]] = metadata["source"]
        docs.append({"content": content, **metadata})

    print(f"[loader] 加载了 {len(docs)} 个去重文档")
    return docs
