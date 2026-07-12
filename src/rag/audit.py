"""知识库元数据、来源和主题覆盖审计。"""

import argparse
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import httpx

from src.rag.loader import load_documents


_EXPECTED_CATEGORIES = {
    "platform_rules",
    "industry_methodology",
    "trend_data",
    "historical_reports",
    "competitor_analysis",
}
_EXPECTED_PLATFORMS = {"bilibili", "douyin", "kuaishou", "xiaohongshu"}
_TOPIC_KEYWORDS = {
    "hook": ("钩子", "开头", "黄金3秒"),
    "script": ("脚本", "内容结构"),
    "topic_selection": ("选题",),
    "cover_title": ("封面", "标题"),
    "metrics": ("完播率", "互动率", "数据指标"),
    "competitor": ("竞品", "对标账号"),
    "commerce": ("电商", "直播带货", "转化"),
}


def _valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _check_url(url: str, timeout: float = 8.0) -> dict:
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            response = client.head(url)
            if response.status_code in {403, 405} or response.status_code >= 500:
                response = client.get(url, headers={"Range": "bytes=0-1024"})
        status_code = response.status_code
        if status_code < 400:
            state = "reachable"
        elif status_code in {401, 403, 405, 412, 429}:
            state = "access_limited"
        elif status_code in {404, 410}:
            state = "dead"
        else:
            state = "unknown"
        return {
            "url": url,
            "ok": state in {"reachable", "access_limited"},
            "state": state,
            "status_code": status_code,
        }
    except Exception as exc:
        return {"url": url, "ok": False, "state": "unknown", "error": str(exc)}


def build_audit(knowledge_dir: str = "knowledge", check_urls: bool = False) -> dict:
    docs = load_documents(knowledge_dir)
    category_counts = Counter(doc["category"] for doc in docs)
    platform_counts = Counter(doc["platform"] for doc in docs)
    content_type_counts = Counter(doc["content_type"] for doc in docs)
    source_tier_counts = Counter(doc["source_tier"] for doc in docs)
    missing_sources = [doc["source"] for doc in docs if not doc["source_urls"]]
    invalid_urls = sorted({
        url
        for doc in docs
        for url in doc["source_urls"]
        if not _valid_url(url)
    })

    url_owners: dict[str, list[str]] = defaultdict(list)
    for doc in docs:
        for url in doc["source_urls"]:
            url_owners[url].append(doc["source"])
    reused_urls = {
        url: owners
        for url, owners in url_owners.items()
        if len(owners) > 1
    }

    searchable_text = "\n".join(f"{doc['title']}\n{doc['content']}" for doc in docs).lower()
    missing_topics = [
        topic
        for topic, keywords in _TOPIC_KEYWORDS.items()
        if not any(keyword.lower() in searchable_text for keyword in keywords)
    ]
    missing_categories = sorted(_EXPECTED_CATEGORIES - set(category_counts))
    platform_rule_platforms = {
        doc["platform"]
        for doc in docs
        if doc["category"] == "platform_rules"
    }
    missing_platform_rules = sorted(_EXPECTED_PLATFORMS - platform_rule_platforms)

    url_checks = []
    if check_urls:
        urls = sorted(url_owners)
        with ThreadPoolExecutor(max_workers=min(8, len(urls) or 1)) as pool:
            url_checks = list(pool.map(_check_url, urls))

    issues = []
    if missing_sources:
        issues.append(f"{len(missing_sources)} 篇文档没有可追溯 URL")
    if invalid_urls:
        issues.append(f"{len(invalid_urls)} 个 URL 格式无效")
    if missing_categories:
        issues.append(f"缺少分类: {', '.join(missing_categories)}")
    if missing_platform_rules:
        issues.append(f"缺少平台规则: {', '.join(missing_platform_rules)}")
    if missing_topics:
        issues.append(f"缺少主题: {', '.join(missing_topics)}")
    dead_checks = [item for item in url_checks if item["state"] == "dead"]
    if dead_checks:
        issues.append(f"{len(dead_checks)} 个来源链接确认失效")

    return {
        "audited_at": date.today().isoformat(),
        "knowledge_dir": str(Path(knowledge_dir)),
        "document_count": len(docs),
        "category_counts": dict(sorted(category_counts.items())),
        "platform_counts": dict(sorted(platform_counts.items())),
        "content_type_counts": dict(sorted(content_type_counts.items())),
        "source_tier_counts": dict(sorted(source_tier_counts.items())),
        "documents_without_source_urls": missing_sources,
        "invalid_urls": invalid_urls,
        "reused_source_urls": reused_urls,
        "missing_categories": missing_categories,
        "missing_platform_rules": missing_platform_rules,
        "missing_topics": missing_topics,
        "url_checks": url_checks,
        "issues": issues,
        "ready": not issues,
    }


def render_markdown(audit: dict) -> str:
    lines = [
        "# 知识库覆盖与来源审计",
        "",
        f"- 审计日期：{audit['audited_at']}",
        f"- 文档数：{audit['document_count']}",
        f"- 门禁状态：{'通过' if audit['ready'] else '未通过'}",
        "",
        "## 分类覆盖",
        "",
    ]
    lines.extend(f"- {name}: {count}" for name, count in audit["category_counts"].items())
    lines.extend(["", "## 平台覆盖", ""])
    lines.extend(f"- {name}: {count}" for name, count in audit["platform_counts"].items())
    lines.extend(["", "## 待处理问题", ""])
    if audit["issues"]:
        lines.extend(f"- {issue}" for issue in audit["issues"])
    else:
        lines.append("- 无")
    if audit["documents_without_source_urls"]:
        lines.extend(["", "### 缺少来源 URL 的文档", ""])
        lines.extend(f"- `{source}`" for source in audit["documents_without_source_urls"])
    if audit["missing_platform_rules"]:
        lines.extend(["", "### 平台规则覆盖缺口", ""])
        lines.extend(f"- {platform}" for platform in audit["missing_platform_rules"])
    if audit["url_checks"]:
        lines.extend(["", "## 在线链接检查", ""])
        for item in audit["url_checks"]:
            status = item.get("status_code", item.get("error", "unknown"))
            lines.append(f"- {item['state'].upper()} `{item['url']}` ({status})")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-dir", default="knowledge")
    parser.add_argument("--check-urls", action="store_true")
    parser.add_argument("--json-output", default="src/eval/results/knowledge_audit.json")
    parser.add_argument("--markdown-output", default="docs/knowledge-coverage.md")
    args = parser.parse_args()

    audit = build_audit(args.knowledge_dir, check_urls=args.check_urls)
    json_path = Path(args.json_output)
    markdown_path = Path(args.markdown_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(audit), encoding="utf-8")
    print(render_markdown(audit))


if __name__ == "__main__":
    main()
