import json
import re
from pathlib import PurePath

from src.rag.embedder import get_or_create_collection


_QUERY_EXPANSIONS = {
    "开头": ("开头", "hook", "钩子", "黄金3秒"),
    "aida": ("aida",),
    "脚本": ("脚本", "结构", "模板"),
    "选题": ("选题",),
    "竞品": ("竞品", "对标"),
    "同类账号": ("竞品", "对标", "账号"),
    "标题": ("标题", "文案"),
    "封面": ("封面",),
    "完播率": ("完播率",),
    "食品": ("食品", "美食"),
    "美食": ("美食",),
    "美妆": ("美妆",),
    "热点": ("热点", "趋势", "话题"),
    "违规": ("违规", "审核", "限流"),
    "审核": ("审核", "违规", "限流"),
    "流量分配": ("流量池", "推荐", "分发"),
    "流量分发": ("流量", "推荐", "分发"),
    "推荐算法": ("推荐", "算法"),
    "直播带货": ("直播", "带货", "电商"),
    "3c": ("3c", "数码", "电子"),
    "发展方向": ("趋势", "发展"),
    "共同特征": ("共同特征", "规律", "特征"),
    "规律": ("规律", "特征"),
    "数据表现": ("数据", "指标"),
    "快手": ("快手",),
    "抖音": ("抖音",),
    "b站": ("b站", "bilibili"),
}

_STOP_FRAGMENTS = (
    "短视频", "视频", "怎么", "什么", "最近", "当前", "分析", "有没有",
    "一下", "一个", "里的", "有什么", "如何", "行业", "过去一年", "各平台",
    "是", "的", "里", "用在", "给我", "想要",
)

_SOURCE_TIER_BONUS = {
    "official": 0.15,
    "research": 0.10,
    "industry": 0.05,
    "secondary": 0.0,
    "internal": -0.10,
}


def _query_terms(query: str) -> list[str]:
    normalized = query.lower()
    terms: list[str] = []
    for trigger, expansions in _QUERY_EXPANSIONS.items():
        if trigger in normalized:
            terms.extend(expansions)

    cleaned = normalized
    for fragment in _STOP_FRAGMENTS:
        cleaned = cleaned.replace(fragment, " ")
    terms.extend(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", cleaned))
    return list(dict.fromkeys(term for term in terms if len(term) > 1))


def _lexical_score(query: str, document: str, source: str) -> float:
    terms = _query_terms(query)
    if not terms:
        return 0.0
    haystack = f"{source}\n{document}".lower()
    filename = PurePath(source).name.lower()
    content_hits = sum(1 for term in terms if term in haystack)
    filename_hits = sum(1 for term in terms if term in filename)
    return (content_hits + 0.5 * filename_hits) / len(terms)


def _source_urls(metadata: dict) -> list[str]:
    raw = metadata.get("source_urls_json", "")
    if raw:
        try:
            value = json.loads(raw)
            if isinstance(value, list):
                return [str(url) for url in value if url]
        except (json.JSONDecodeError, TypeError):
            pass
    primary = metadata.get("source_url", "")
    return [primary] if primary else []


def retrieve_with_metadata(query: str, top_k: int = 5, platform: str = None) -> list[dict]:
    """混合检索并按来源去重，返回内容与来源元数据。"""
    collection = get_or_create_collection("knowledge")

    where = None
    if platform:
        where = {"platform": {"$in": [platform, "generic"]}}

    candidate_count = max(top_k * 4, 20)
    semantic = collection.query(
        query_texts=[query],
        n_results=candidate_count,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    lexical = collection.get(
        where=where,
        include=["documents", "metadatas"],
    )

    by_source: dict[str, dict] = {}
    semantic_docs = semantic.get("documents", [[]])[0]
    semantic_meta = semantic.get("metadatas", [[]])[0]
    semantic_distances = semantic.get("distances", [[]])[0]
    for rank, (document, metadata, distance) in enumerate(
        zip(semantic_docs, semantic_meta, semantic_distances), start=1
    ):
        source = metadata.get("source", "")
        if source not in by_source:
            by_source[source] = {
                "content": document,
                "source": source,
                "platform": metadata.get("platform", "generic"),
                "title": metadata.get("title", ""),
                "category": metadata.get("category", ""),
                "heading_path": metadata.get("heading_path", ""),
                "source_url": metadata.get("source_url", ""),
                "source_urls": _source_urls(metadata),
                "source_tier": metadata.get("source_tier", "internal"),
                "provenance_status": metadata.get("provenance_status", "missing"),
                "semantic_rank": rank,
                "distance": distance,
                "lexical_score": 0.0,
            }

    for document, metadata in zip(lexical.get("documents", []), lexical.get("metadatas", [])):
        source = metadata.get("source", "")
        score = _lexical_score(query, document, source)
        current = by_source.get(source)
        if current is None:
            current = {
                "content": document,
                "source": source,
                "platform": metadata.get("platform", "generic"),
                "title": metadata.get("title", ""),
                "category": metadata.get("category", ""),
                "heading_path": metadata.get("heading_path", ""),
                "source_url": metadata.get("source_url", ""),
                "source_urls": _source_urls(metadata),
                "source_tier": metadata.get("source_tier", "internal"),
                "provenance_status": metadata.get("provenance_status", "missing"),
                "semantic_rank": candidate_count + 1,
                "distance": None,
                "lexical_score": score,
            }
            by_source[source] = current
        elif score > current["lexical_score"]:
            current["content"] = document
            current["lexical_score"] = score

    for item in by_source.values():
        semantic_score = 1 / item["semantic_rank"]
        source_bonus = _SOURCE_TIER_BONUS.get(item.get("source_tier", "internal"), 0.0)
        platform_bonus = 0.15 if platform and item.get("platform") == platform else 0.0
        item["score"] = (
            item["lexical_score"]
            + 0.25 * semantic_score
            + source_bonus
            + platform_bonus
        )

    return sorted(by_source.values(), key=lambda item: item["score"], reverse=True)[:top_k]


def retrieve(query: str, top_k: int = 5, platform: str = None) -> list[str]:
    """从 ChromaDB 检索相关文档。

    Args:
        query: 检索查询
        top_k: 返回数量
        platform: 平台过滤（bilibili/douyin/kuaishou），None 表示不过滤
    """
    results = retrieve_with_metadata(query, top_k, platform)
    documents = [item["content"] for item in results]
    print(f"[retriever] 检索到 {len(documents)} 条结果 (platform={platform})")
    return documents
