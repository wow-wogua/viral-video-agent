from mcp.server.fastmcp import FastMCP

from src.tools.rag_retrieval import rag_search
from src.tools.search import search_videos
from src.tools.transcript import get_transcript
from src.tools.trend import get_trend_data


mcp = FastMCP(
    "viral-video-tools",
    host="0.0.0.0",
    port=8001,
    sse_path="/sse",
    message_path="/messages/",
)


@mcp.tool(name="search_videos")
async def search_videos_tool(keyword: str, platforms: list[str], limit: int = 10) -> list[dict]:
    """搜索短视频平台的热门视频数据。"""
    return await search_videos(keyword, platforms, limit)


@mcp.tool(name="get_transcript")
async def get_transcript_tool(video_url: str) -> str | None:
    """获取视频转写文本。"""
    return await get_transcript(video_url)


@mcp.tool(name="rag_search")
async def rag_search_tool(query: str, top_k: int = 5) -> list[str]:
    """从项目知识库检索参考文档。"""
    return await rag_search(query, top_k)


@mcp.tool(name="get_trend_data")
async def get_trend_data_tool(video_id: str, platform: str = "bilibili") -> dict:
    """获取视频历史趋势数据；真实数据源不可用时返回 unavailable。"""
    return await get_trend_data(video_id, platform)


if __name__ == "__main__":
    mcp.run(transport="sse")
