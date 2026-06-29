TOOL_REGISTRY = {
    "search_videos": {
        "description": "搜索短视频平台数据",
        "params": ["keyword", "platforms", "limit"],
    },
    "get_transcript": {
        "description": "获取视频转写文本",
        "params": ["video_url"],
    },
    "rag_search": {
        "description": "从知识库检索相关文档",
        "params": ["query", "top_k"],
    },
    "get_trend_data": {
        "description": "获取视频历史趋势数据（播放量/点赞/评论趋势）",
        "params": ["video_id", "platform"],
    },
}

def get_available_tools() -> list[dict]:
    return [
        {"name": name, **info}
        for name, info in TOOL_REGISTRY.items()
    ]