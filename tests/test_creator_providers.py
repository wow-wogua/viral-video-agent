import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from src.intelligence.contracts import CreatorSampleStatus
from src.intelligence.creator_providers import (
    BilibiliDevelopmentCreatorProvider,
    FixtureCreatorProvider,
    ImportCreatorProvider,
)


FIXTURE = Path(__file__).parent / "fixtures" / "creator_provider" / "import_creator_sample.json"
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


def upload_item(index: int, *, days: int) -> dict:
    return {
        "bvid": f"BV{index:010d}",
        "mid": 90001,
        "author": "sanitized creator",
        "title": f"sanitized upload {index}",
        "description": "sanitized description",
        "created": int((NOW - timedelta(days=days)).timestamp()),
        "length": "03:20",
        "pic": "https://example.test/cover.png",
        "play": 10000 + index,
        "comment": 20,
        "video_review": 30,
        "typeid": 1,
    }


def transport(*, upload_count=3, follower_status=200, uploads_status=200, omit_list=False, raise_timeout=False):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "cookie" not in request.headers
        if raise_timeout and request.url.path.endswith("/arc/search"):
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if request.url.path.endswith("/nav"):
            return httpx.Response(200, json=nav_payload(), request=request)
        if request.url.path.endswith("/arc/search"):
            if uploads_status != 200:
                return httpx.Response(uploads_status, text="unavailable", request=request)
            data = {"is_risk": False}
            if not omit_list:
                data["list"] = {"vlist": [upload_item(index + 1, days=index * 35) for index in range(upload_count)]}
            return httpx.Response(200, json={"code": 0, "data": data}, request=request)
        if request.url.path.endswith("/relation/stat"):
            if follower_status != 200:
                return httpx.Response(follower_status, text="unavailable", request=request)
            return httpx.Response(200, json={"code": 0, "data": {"follower": 20000}}, request=request)
        raise AssertionError(request.url)

    return httpx.MockTransport(handler), requests


@pytest.mark.asyncio
async def test_development_creator_provider_success_caps_latest_twenty_and_computes_windows():
    mock, requests = transport(upload_count=25)
    provider = BilibiliDevelopmentCreatorProvider(
        client=httpx.AsyncClient(transport=mock),
        min_interval_seconds=0,
        now=lambda: NOW,
    )
    sample = await provider.fetch_creator("90001", "sanitized creator")
    await provider.close()
    assert sample.status == CreatorSampleStatus.SUCCESS
    assert len(sample.uploads) == 20
    assert sample.recent_30d_upload_count == 1
    assert sample.recent_90d_upload_count == 3
    assert sample.follower_count == 20000
    assert all(video.coin is None and video.share is None and video.like is None for video in sample.uploads)
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_development_creator_provider_partial_when_follower_data_is_missing():
    mock, _ = transport(follower_status=500)
    provider = BilibiliDevelopmentCreatorProvider(client=httpx.AsyncClient(transport=mock), min_interval_seconds=0, now=lambda: NOW)
    sample = await provider.fetch_creator("90001", "sanitized creator")
    assert sample.status == CreatorSampleStatus.PARTIAL
    assert sample.uploads
    assert sample.follower_count is None
    assert "follower" in sample.missing_reason


@pytest.mark.asyncio
async def test_development_creator_provider_missing_failed_timeout_and_cancelled_states():
    provider = BilibiliDevelopmentCreatorProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("network should not be used"))), min_interval_seconds=0, now=lambda: NOW)
    missing = await provider.fetch_creator("", "sanitized creator")
    assert missing.status == CreatorSampleStatus.MISSING

    failed_transport, _ = transport(uploads_status=500)
    failed_provider = BilibiliDevelopmentCreatorProvider(client=httpx.AsyncClient(transport=failed_transport), min_interval_seconds=0, now=lambda: NOW)
    failed = await failed_provider.fetch_creator("90001", "sanitized creator")
    assert failed.status == CreatorSampleStatus.FAILED

    timeout_transport, _ = transport(raise_timeout=True)
    timeout_provider = BilibiliDevelopmentCreatorProvider(client=httpx.AsyncClient(transport=timeout_transport), min_interval_seconds=0, now=lambda: NOW)
    timed_out = await timeout_provider.fetch_creator("90001", "sanitized creator")
    assert timed_out.status == CreatorSampleStatus.TIMEOUT

    cancelled = await provider.fetch_creator("90001", "sanitized creator", cancel_check=lambda: _true())
    assert cancelled.status == CreatorSampleStatus.CANCELLED


async def _true():
    return True


@pytest.mark.asyncio
async def test_development_creator_provider_missing_upload_list_is_failed_not_empty_success():
    mock, _ = transport(omit_list=True)
    provider = BilibiliDevelopmentCreatorProvider(client=httpx.AsyncClient(transport=mock), min_interval_seconds=0, now=lambda: NOW)
    sample = await provider.fetch_creator("90001", "sanitized creator")
    assert sample.status == CreatorSampleStatus.FAILED
    assert sample.uploads == []
    assert sample.missing_reason == "uploads_list_missing"


@pytest.mark.asyncio
async def test_import_creator_provider_preserves_source_lineage_and_never_fabricates_fields():
    provider = ImportCreatorProvider.from_json(FIXTURE.read_text(encoding="utf-8"))
    sample = await provider.fetch_creator("90001", "ignored")
    assert sample.provider_name == "import"
    assert sample.provider_kind == "import"
    assert sample.source_provider_name == "public-page-capture"
    assert sample.source_provider_version == "capture-v1"
    assert len(sample.uploads) == 3
    assert sample.uploads[0].coin is None
    absent = await provider.fetch_creator("99999", "absent")
    assert absent.status == CreatorSampleStatus.MISSING


def test_import_creator_json_rejects_unknown_fields_duplicates_and_more_than_twenty_uploads():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["unknown"] = True
    with pytest.raises(ValidationError):
        ImportCreatorProvider.from_json(payload)

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["creators"].append(payload["creators"][0])
    with pytest.raises(ValidationError):
        ImportCreatorProvider.from_json(payload)

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["creators"][0]["uploads"] = [
        {**payload["creators"][0]["uploads"][0], "bvid": f"BV{index:010d}"}
        for index in range(1, 22)
    ]
    with pytest.raises(ValidationError):
        ImportCreatorProvider.from_json(payload)


@pytest.mark.asyncio
async def test_import_creator_csv_is_strict_and_fixture_provider_is_distinct():
    csv_payload = "\n".join([
        "source_name,provider_version,creator_mid,creator_name,profile_url,status,observed_at,source_url,source_provider_name,source_provider_version,follower_count,missing_reason,raw_payload_hash,bvid,title,video_source_url,description,tags,partition,published_at,duration_seconds,cover_url,view,like,coin,favorite,reply,share,danmaku,missing_fields",
        "sanitized-capture,capture-v1,90001,sanitized creator,https://example.test/90001,success,2026-07-16T12:00:00Z,https://example.test/90001/uploads,public-page,capture-v1,20000,,,BV1000000101,sanitized upload,https://www.bilibili.com/video/BV1000000101,,topic,,2026-07-10T12:00:00Z,,,,,,,,,,coin|share",
    ])
    provider = ImportCreatorProvider.from_csv(csv_payload)
    sample = await provider.fetch_creator("90001", "sanitized creator")
    assert sample.status == CreatorSampleStatus.SUCCESS
    assert len(sample.uploads) == 1
    fixture = FixtureCreatorProvider.from_json(FIXTURE.read_text(encoding="utf-8"))
    assert fixture.capabilities.provider_kind == "fixture"

    bad_csv = csv_payload.replace("missing_fields", "unknown_column")
    with pytest.raises(ValueError, match="unknown columns"):
        ImportCreatorProvider.from_csv(bad_csv)
