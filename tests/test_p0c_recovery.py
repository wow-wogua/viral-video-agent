import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from scripts.run_p0c_evaluation import capture_creator_targets
from src.intelligence.creator_providers import (
    CREATOR_RISK_CONTROL_THRESHOLD,
    BilibiliDevelopmentCreatorProvider,
)


NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)


def nav_payload():
    return {
        "code": -101,
        "data": {
            "wbi_img": {
                "img_url": "https://i0.hdslb.com/bfs/wbi/" + "a" * 64 + ".png",
                "sub_url": "https://i0.hdslb.com/bfs/wbi/" + "b" * 64 + ".png",
            }
        },
    }


def upload_payload(mid: str):
    return {
        "code": 0,
        "data": {
            "is_risk": False,
            "list": {
                "vlist": [{
                    "bvid": f"BV{int(mid):010d}",
                    "mid": int(mid),
                    "author": "sanitized creator",
                    "title": "sanitized upload",
                    "created": int((NOW - timedelta(days=1)).timestamp()),
                    "length": "03:20",
                    "play": 10000,
                    "comment": 20,
                    "video_review": 30,
                }]
            },
        },
    }


@pytest.mark.asyncio
async def test_capture_progress_stops_at_risk_circuit_marks_unattempted_and_resumes_without_requests(tmp_path):
    requests = []

    def risk_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/nav"):
            return httpx.Response(200, json=nav_payload(), request=request)
        return httpx.Response(412, text="risk control", request=request)

    targets = [(str(91000 + index), "sanitized creator") for index in range(5)]
    provider = BilibiliDevelopmentCreatorProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(risk_handler)),
        min_interval_seconds=0,
        now=lambda: NOW,
    )
    result = await capture_creator_targets(
        targets,
        tmp_path,
        capture_round_id="sanitized-round-1",
        provider=provider,
    )
    assert result.summary["capture_status"] == "circuit_open"
    assert result.summary["attempted_count"] == CREATOR_RISK_CONTROL_THRESHOLD
    assert result.summary["not_attempted_count"] == 5 - CREATOR_RISK_CONTROL_THRESHOLD
    assert len(requests) == 1 + CREATOR_RISK_CONTROL_THRESHOLD
    progress = json.loads((tmp_path / "creator-capture-progress.json").read_text(encoding="utf-8"))
    assert progress["schema_version"] == "creator-capture-progress.p0-c.2"
    assert progress["circuit"]["state"] == "open"
    assert not (tmp_path / "creator-capture-progress.json.tmp").exists()
    progress["creators"] = progress["creators"][:CREATOR_RISK_CONTROL_THRESHOLD]
    (tmp_path / "creator-capture-progress.json").write_text(
        json.dumps(progress, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    resumed_requests = []

    def must_not_request(request: httpx.Request) -> httpx.Response:
        resumed_requests.append(request)
        raise AssertionError("an open capture round must not resume network requests")

    resumed_provider = BilibiliDevelopmentCreatorProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(must_not_request)),
        min_interval_seconds=0,
        now=lambda: NOW,
    )
    resumed = await capture_creator_targets(
        targets,
        tmp_path,
        capture_round_id="sanitized-round-1",
        provider=resumed_provider,
    )
    assert resumed.summary == result.summary
    assert len(resumed.creators) == len(targets)
    assert resumed_requests == []


@pytest.mark.asyncio
async def test_completed_capture_is_idempotent_and_new_round_requires_new_directory(tmp_path):
    requests = []

    def success_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/nav"):
            return httpx.Response(200, json=nav_payload(), request=request)
        if request.url.path.endswith("/arc/search"):
            return httpx.Response(200, json=upload_payload(request.url.params["mid"]), request=request)
        return httpx.Response(200, json={"code": 0, "data": {"follower": 20000}}, request=request)

    targets = [("92001", "sanitized creator"), ("92002", "sanitized creator")]
    provider = BilibiliDevelopmentCreatorProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(success_handler)),
        min_interval_seconds=0,
        now=lambda: NOW,
    )
    first = await capture_creator_targets(
        targets,
        tmp_path,
        capture_round_id="sanitized-round-2",
        provider=provider,
    )
    assert first.summary["capture_status"] == "completed"
    initial_request_count = len(requests)

    resumed_provider = BilibiliDevelopmentCreatorProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(success_handler)),
        min_interval_seconds=0,
        now=lambda: NOW,
    )
    second = await capture_creator_targets(
        targets,
        tmp_path,
        capture_round_id="sanitized-round-2",
        provider=resumed_provider,
    )
    assert second.summary == first.summary
    assert len(requests) == initial_request_count

    with pytest.raises(ValueError, match="new output directory and round ID"):
        await capture_creator_targets(
            targets,
            tmp_path,
            capture_round_id="sanitized-round-3",
            provider=resumed_provider,
        )
