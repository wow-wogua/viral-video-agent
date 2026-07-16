"""Legacy MCP search tool backed by the replaceable P0-B provider layer."""

from __future__ import annotations

from src.intelligence.contracts import SearchRequest
from src.intelligence.providers import BilibiliDevelopmentSearchProvider
from src.intelligence.search_service import execute_search_snapshot


def _legacy_video(video) -> dict:
    return {
        "platform": "bilibili",
        "bvid": video.bvid,
        "aid": video.aid,
        "title": video.title,
        "author": video.creator_name or "",
        "mid": video.creator_mid,
        "view": video.view,
        "views": video.view,
        "play": video.view,
        "like": video.like,
        "likes": video.like,
        "comment": video.reply,
        "comments": video.reply,
        "reply": video.reply,
        "share": video.share,
        "shares": video.share,
        "coin": video.coin,
        "favorite": video.favorite,
        "danmaku": video.danmaku,
        "duration": video.duration_seconds,
        "pubdate": video.published_at.isoformat() if video.published_at else None,
        "url": video.source_url,
        "source_page": video.source_page,
        "source_rank": video.source_rank,
        "missing_fields": video.missing_fields,
    }


async def search_bilibili(keyword: str, limit: int = 10) -> list[dict]:
    """Return at most the first public search page; no ranking/hot-pool substitution."""

    provider = BilibiliDevelopmentSearchProvider()
    request = SearchRequest(
        keyword=keyword or "热门",
        max_pages=1,
        idempotency_key=f"legacy-search-{(keyword or 'popular')[:100]}",
    )
    try:
        bundle = await execute_search_snapshot(provider, request)
    finally:
        await provider.close()
    return [_legacy_video(video) for video in bundle.videos[:limit]]


async def search_videos(keyword: str, platforms: list[str], limit: int = 10) -> list[dict]:
    """Compatibility entrypoint. Real search remains Bilibili-only."""

    if platforms != ["bilibili"]:
        raise ValueError("only bilibili is supported")
    return await search_bilibili(keyword, limit)
