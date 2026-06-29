import httpx
import hashlib
import time
import asyncio
from src.config import XFYUN_APPID, XFYUN_SECRET_KEY


async def get_transcript(video_url: str) -> str | None:
    """获取视频转写文本。调用讯飞语音转写 API。"""
    if not XFYUN_APPID or not XFYUN_SECRET_KEY:
        print("[transcript] 讯飞 API 未配置，跳过转写")
        return None

    try:
        ts = str(int(time.time()))
        sign_str = XFYUN_APPID + ts
        sign = hashlib.md5((sign_str + XFYUN_SECRET_KEY).encode()).hexdigest()

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://raasr.xfyun.cn/v2/api/submit",
                params={"appid": XFYUN_APPID, "ts": ts, "sign": sign},
                json={"url": video_url},
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") == "00000":
                task_id = result.get("data", {}).get("task_id", "")
                return await _poll_result(client, task_id, ts, sign)
            else:
                print(f"[transcript] 提交失败: {result}")
                return None
    except Exception as e:
        print(f"[transcript] 转写失败: {video_url}, 错误: {e}")
        return None


async def _poll_result(client, task_id: str, ts: str, sign: str) -> str | None:
    """轮询获取转写结果。"""
    for _ in range(30):
        await asyncio.sleep(10)
        resp = await client.get(
            "https://raasr.xfyun.cn/v2/api/result",
            params={"appid": XFYUN_APPID, "ts": ts, "sign": sign, "task_id": task_id},
        )
        result = resp.json()
        if result.get("code") == "00000":
            return result.get("data", {}).get("result", "")
    return None
