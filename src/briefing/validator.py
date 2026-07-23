import json
from collections.abc import Callable

from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from src.briefing.schemas import BriefDecision, BriefOption, TopicSpec
from src.gateway.cost_tracker import cost_tracker
from src.gateway.llm_router import get_llm
from src.prompts.manager import prompt_manager


PROMPT_VERSION = "brief-validator.vnext.1"


def _parse_json_object(text: str) -> dict:
    clean = (text or "").strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(clean)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start, end = clean.find("{"), clean.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(clean[start:end + 1])
                return value if isinstance(value, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def _response_text(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content or "")


def conservative_clarification(round_number: int) -> BriefDecision:
    """Safe fallback: narrow the scope instead of silently widening it."""
    return BriefDecision(
        need_clarification=True,
        question="为了避免扩大研究范围，请确认是否只纳入持续发布该主题内容的专业账号？",
        options=[
            BriefOption(
                id="strict_specialist",
                label="只纳入持续做该主题的账号",
                description="排除只偶尔发布相关视频的综合账号。",
            ),
            BriefOption(
                id="include_generalist",
                label="也纳入综合型账号",
                description="只要有稳定的相关内容，也可以纳入综合账号。",
            ),
        ],
        allow_custom=True,
        verification=f"第 {round_number} 轮仍缺少账号范围定义，默认不扩大搜索范围。",
        confidence=0.25,
    )


def conservative_topic_spec(query: str, history: list[dict]) -> TopicSpec:
    topic = query.strip()[:120] or "未命名主题"
    assumptions = [
        "已达到最多两轮澄清，仍无法完全确认全部纳入条件。",
        "默认只纳入持续发布主题相关内容的账号，并保留明确的范围假设。",
    ]
    for item in history[-2:]:
        answer = item.get("custom_answer") or item.get("selected_option_id")
        if answer:
            assumptions.append(f"用户补充范围：{str(answer).strip()[:160]}")
    return TopicSpec(
        topic=topic,
        target_content=[topic],
        include_creator_types=["reviewer", "educator"],
        exclude_content=[],
        time_window_days=365,
        allow_generalist=False,
        competitor_definition=f"持续发布与“{topic}”直接相关内容的账号",
        platform="bilibili",
        assumptions=assumptions[:8],
        confidence=0.4,
    )


class BriefValidator:
    def __init__(self, llm_factory: Callable[[], object] | None = None):
        self.llm_factory = llm_factory or (lambda: get_llm("planner"))

    async def validate(self, query: str, history: list[dict], round_number: int) -> BriefDecision:
        prompt = prompt_manager.get(
            "brief_validator",
            prompt_version=PROMPT_VERSION,
            user_request=query,
            clarification_round=round_number,
            max_rounds=2,
            prior_answers=json.dumps(history, ensure_ascii=False),
        )
        try:
            response = await self.llm_factory().ainvoke([HumanMessage(content=prompt)])
            cost_tracker.log_response(response)
            decision = BriefDecision.model_validate(_parse_json_object(_response_text(response)))
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError):
            decision = conservative_clarification(round_number)
        except Exception:
            # Provider/network failures must not turn an ambiguous brief into a broad search.
            decision = conservative_clarification(round_number)

        return decision
