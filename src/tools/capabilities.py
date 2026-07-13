"""运行时工具能力、参数校验与 Researcher Prompt 描述。"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from src.config import ENABLE_MOCK_TOOLS
from src.tools.transcript import transcript_capability


class ToolUnavailableError(ValueError):
    """工具或目标平台在当前运行环境不可用。"""


class SearchVideosParams(BaseModel):
    keyword: str = ""
    platforms: list[str] = Field(default_factory=lambda: ["bilibili"])
    limit: int = Field(default=10, ge=1, le=20)

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value):
        if value is None:
            return 10
        return min(20, max(1, int(value)))

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, value: list[str]) -> list[str]:
        aliases = {"b站": "bilibili", "哔哩哔哩": "bilibili"}
        normalized = list(dict.fromkeys(aliases.get(item.lower(), item.lower()) for item in value))
        unsupported = [item for item in normalized if item != "bilibili"]
        if unsupported:
            raise ValueError(f"unsupported platforms: {', '.join(unsupported)}")
        return normalized or ["bilibili"]


class RagSearchParams(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)
    platform: Literal["bilibili", "douyin", "kuaishou", "xiaohongshu", "generic"] | None = None


class TranscriptParams(BaseModel):
    video_url: str = Field(min_length=1)


class TrendParams(BaseModel):
    video_id: str = Field(min_length=1)
    platform: Literal["bilibili"] = "bilibili"


@dataclass(frozen=True)
class ToolCapability:
    name: str
    description: str
    params_model: type[BaseModel]
    enabled: bool
    availability: str
    supported_platforms: tuple[str, ...] = ()


def get_tool_capabilities() -> dict[str, ToolCapability]:
    transcript_enabled, transcript_provider = transcript_capability()
    return {
        "search_videos": ToolCapability(
            name="search_videos",
            description="搜索B站当前/近期热门视频样本，单次最多20条",
            params_model=SearchVideosParams,
            enabled=True,
            availability="real",
            supported_platforms=("bilibili",),
        ),
        "rag_search": ToolCapability(
            name="rag_search",
            description="检索本地知识库中的平台规则、方法论和历史案例",
            params_model=RagSearchParams,
            enabled=True,
            availability="local",
            supported_platforms=("bilibili", "douyin", "kuaishou", "xiaohongshu", "generic"),
        ),
        "get_transcript": ToolCapability(
            name="get_transcript",
            description=f"通过已配置的 {transcript_provider} 服务转写公开B站视频",
            params_model=TranscriptParams,
            enabled=transcript_enabled,
            availability=transcript_provider,
            supported_platforms=("bilibili",),
        ),
        "get_trend_data": ToolCapability(
            name="get_trend_data",
            description="获取指定B站视频的演示趋势数据",
            params_model=TrendParams,
            enabled=ENABLE_MOCK_TOOLS,
            availability="mock" if ENABLE_MOCK_TOOLS else "unavailable",
            supported_platforms=("bilibili",),
        ),
    }


def get_available_tool_names() -> set[str]:
    return {name for name, capability in get_tool_capabilities().items() if capability.enabled}


def render_available_tools() -> str:
    """只渲染当前可调用工具；mock 能力会显式标记。"""
    lines = []
    for capability in get_tool_capabilities().values():
        if not capability.enabled:
            continue
        params = ", ".join(capability.params_model.model_fields)
        suffix = " [仅演示mock]" if capability.availability == "mock" else ""
        platforms = (
            f"；支持平台: {', '.join(capability.supported_platforms)}"
            if capability.supported_platforms
            else ""
        )
        lines.append(f"- {capability.name}({params}): {capability.description}{platforms}{suffix}")
    lines.append('- none: 当前步骤不需要新增外部数据或资料')
    return "\n".join(lines)


def normalize_tool_params(tool_name: str, params: dict | None) -> dict:
    capabilities = get_tool_capabilities()
    capability = capabilities.get(tool_name)
    if capability is None:
        raise ToolUnavailableError(f"unknown tool: {tool_name}")
    if not capability.enabled:
        raise ToolUnavailableError(
            f"tool unavailable: {tool_name} ({capability.availability})"
        )
    try:
        return capability.params_model.model_validate(params or {}).model_dump()
    except ValidationError as exc:
        raise ValueError(f"invalid params for {tool_name}: {exc}") from exc


def capability_snapshot() -> list[dict]:
    return [
        {
            "name": capability.name,
            "enabled": capability.enabled,
            "availability": capability.availability,
            "supported_platforms": list(capability.supported_platforms),
        }
        for capability in get_tool_capabilities().values()
    ]
