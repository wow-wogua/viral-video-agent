import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from src.tools.search import search_videos
from src.tools.transcript import get_transcript
from src.tools.rag_retrieval import rag_search
from src.tools.trend import get_trend_data

server = Server("viral-video-tools")

@server.tool("search_videos")
async def search_videos_tool(keyword: str, platforms: list[str], limit: int = 10) -> list[dict]:
    return await search_videos(keyword, platforms, limit)

@server.tool("get_transcript")
async def get_transcript_tool(video_url: str) -> str | None:
    return await get_transcript(video_url)

@server.tool("rag_search")
async def rag_search_tool(query: str, top_k: int = 5) -> list[dict]:
    return await rag_search(query, top_k)

@server.tool("get_trend_data")
async def get_trend_data_tool(video_id: str, platform: str = "bilibili") -> dict:
    return await get_trend_data(video_id, platform)

# SSE transport
sse_transport = SseServerTransport("/messages/")

async def handle_sse(request):
    async with sse_transport.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())

app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)