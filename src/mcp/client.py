from src.tools.search import search_videos
from src.tools.transcript import get_transcript
from src.tools.rag_retrieval import rag_search
from src.tools.trend import get_trend_data

async def call_tool(tool_name: str, params: dict):
    if tool_name == "search_videos":
        return await search_videos(**params)
    elif tool_name == "get_transcript":
        return await get_transcript(**params)
    elif tool_name == "rag_search":
        return await rag_search(**params)
    elif tool_name == "get_trend_data":
        return await get_trend_data(**params)
    else:
        raise ValueError(f"Unknown tool: {tool_name}")