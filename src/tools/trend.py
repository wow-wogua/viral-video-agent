"""
历史趋势数据工具（飞瓜 API 占位符）
====================================
真实数据源尚未接入。默认返回 unavailable；只有显式开启 ENABLE_MOCK_TOOLS 才生成演示数据。

飞瓜 API 文档参考：https://www.feigua.cn/api
接口：GET /api/video/trend
参数：video_id, platform
返回：历史播放量/点赞/评论趋势数据
"""

import os
import random
from datetime import datetime, timedelta
from src.config import ENABLE_MOCK_TOOLS

FEIGUO_API_KEY = os.getenv("FEIGUO_API_KEY", "")


def _generate_mock_trend(video_id: str, platform: str) -> dict:
    """生成 mock 趋势数据（7天）。"""
    base_views = random.randint(10000, 500000)
    base_likes = random.randint(500, 50000)
    base_comments = random.randint(50, 5000)

    daily = []
    for i in range(7):
        date = (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%d")
        growth = 1 + random.uniform(-0.2, 0.5)
        daily.append({
            "date": date,
            "views": int(base_views * growth * (1 + i * 0.1)),
            "likes": int(base_likes * growth * (1 + i * 0.08)),
            "comments": int(base_comments * growth * (1 + i * 0.05)),
            "shares": int(base_likes * 0.1 * growth),
        })

    return {
        "video_id": video_id,
        "platform": platform,
        "period": "7d",
        "daily": daily,
        "summary": {
            "total_views": sum(d["views"] for d in daily),
            "total_likes": sum(d["likes"] for d in daily),
            "total_comments": sum(d["comments"] for d in daily),
            "avg_engagement_rate": round(random.uniform(0.02, 0.15), 4),
            "trend": random.choice(["rising", "stable", "declining"]),
        },
        "source": "mock",
    }


async def get_trend_data(video_id: str, platform: str = "bilibili") -> dict:
    """获取视频历史趋势数据。

    Args:
        video_id: 视频 ID 或 URL
        platform: 平台名（bilibili / douyin / kuaishou）

    Returns:
        趋势数据字典，含每日播放量/点赞/评论和汇总
    """
    if not video_id:
        return {"error": "video_id is required", "source": "unavailable"}

    # ── 真实 Provider 接入点（当前未实现）──
    # 接入时替换下方代码：
    #
    # if FEIGUO_API_KEY:
    #     import httpx
    #     async with httpx.AsyncClient() as client:
    #         resp = await client.get(
    #             "https://api.feigua.cn/api/video/trend",
    #             params={"video_id": video_id, "platform": platform},
    #             headers={"Authorization": f"Bearer {FEIGUO_API_KEY}"},
    #             timeout=10,
    #         )
    #         if resp.status_code == 200:
    #             return resp.json()
    #         return {"error": f"Feigua API error: {resp.status_code}", "source": "feigua"}

    if ENABLE_MOCK_TOOLS:
        print("[trend] ENABLE_MOCK_TOOLS=true，返回仅供演示的 mock 数据")
        return _generate_mock_trend(video_id, platform)

    print("[trend] 真实趋势数据源未接入，拒绝生成随机 mock 数据")
    return {
        "video_id": video_id,
        "platform": platform,
        "source": "unavailable",
        "error": "real trend data provider is not configured",
    }
