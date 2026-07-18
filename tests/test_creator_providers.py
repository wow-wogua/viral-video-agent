import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from src.intelligence.contracts import CreatorSampleStatus
from src.intelligence.creator_providers import (
    CREATOR_RISK_CONTROL_THRESHOLD,
    BilibiliDevelopmentCreatorProvider,
    FixtureCreatorProvider,
    ImportCreatorProvider,
    UAPIDevelopmentCreatorProvider,
    creator_scope_hash,
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
    assert sample.request_audit.attempt_count == 3
    assert sample.request_audit.retry_count == 0
    assert sample.request_audit.final_classification == "success"


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
    failed_provider = BilibiliDevelopmentCreatorProvider(
        client=httpx.AsyncClient(transport=failed_transport),
        max_retries=0,
        min_interval_seconds=0,
        now=lambda: NOW,
    )
    failed = await failed_provider.fetch_creator("90001", "sanitized creator")
    assert failed.status == CreatorSampleStatus.FAILED

    timeout_transport, _ = transport(raise_timeout=True)
    timeout_provider = BilibiliDevelopmentCreatorProvider(
        client=httpx.AsyncClient(transport=timeout_transport),
        max_retries=0,
        min_interval_seconds=0,
        now=lambda: NOW,
    )
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


def uapi_archives_payload(upload_count=3):
    return {
        "total": upload_count,
        "page": 1,
        "size": 20,
        "videos": [{
            "aid": index,
            "bvid": f"BV{index:010d}",
            "title": f"sanitized UAPI upload {index}",
            "cover": "https://example.test/cover.png",
            "duration": 180 + index,
            "play_count": 10000 + index,
            "publish_time": int((NOW - timedelta(days=index)).timestamp()),
            "create_time": int((NOW - timedelta(days=index)).timestamp()),
            "state": 0,
            "is_ugc_pay": 0,
            "is_interactive": False,
        } for index in range(1, upload_count + 1)],
    }


def uapi_userinfo_payload():
    return {
        "mid": 90001,
        "name": "sanitized UAPI creator",
        "follower": 23456,
        "archive_count": 3,
    }


async def no_wait(seconds):
    return None


@pytest.mark.asyncio
async def test_uapi_creator_provider_normalizes_development_only_source_without_leaking_key(capsys):
    secret = "test-uapi-secret"
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == f"Bearer {secret}"
        if request.url.path.endswith("/archives"):
            return httpx.Response(200, json=uapi_archives_payload(), request=request)
        if request.url.path.endswith("/userinfo"):
            return httpx.Response(200, json=uapi_userinfo_payload(), request=request)
        raise AssertionError(request.url)

    provider = UAPIDevelopmentCreatorProvider(
        api_key=secret,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        min_interval_seconds=1.5,
        sleep=no_wait,
        now=lambda: NOW,
    )
    sample = await provider.fetch_creator("90001", "fallback creator")
    assert sample.status == CreatorSampleStatus.SUCCESS
    assert sample.creator_name == "sanitized UAPI creator"
    assert sample.follower_count == 23456
    assert len(sample.uploads) == 3
    assert sample.uploads[0].published_at is not None
    assert sample.uploads[0].view == 10001
    assert sample.uploads[0].like is None
    assert sample.provider_name == "uapi-creator"
    assert sample.provider_kind == "development"
    assert provider.capabilities.requires_api_key
    assert provider.capabilities.commercial_authorization == "development_only"
    assert sample.request_audit.final_classification == "success"
    assert [attempt.operation for attempt in sample.request_audit.attempts] == [
        "uapi_archives", "uapi_userinfo"
    ]
    assert secret not in sample.model_dump_json()
    assert secret not in capsys.readouterr().out
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_uapi_creator_provider_partial_missing_and_missing_authentication_states():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/archives"):
            if request.url.params["mid"] == "40400":
                return httpx.Response(404, json={"code": "NOT_FOUND"}, request=request)
            return httpx.Response(200, json=uapi_archives_payload(), request=request)
        return httpx.Response(502, json={"code": "UPSTREAM_ERROR"}, request=request)

    provider = UAPIDevelopmentCreatorProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
        min_interval_seconds=1.5,
        sleep=no_wait,
        now=lambda: NOW,
    )
    partial = await provider.fetch_creator("90001", "fallback creator")
    assert partial.status == CreatorSampleStatus.PARTIAL
    assert partial.uploads
    assert partial.follower_count is None
    assert "uapi_userinfo_http_502" in partial.missing_reason

    missing = await provider.fetch_creator("40400", "missing creator")
    assert missing.status == CreatorSampleStatus.MISSING
    assert missing.request_audit.final_classification == "not_found"

    no_auth_requests = []
    no_auth = UAPIDevelopmentCreatorProvider(
        api_key="",
        client=httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: no_auth_requests.append(request) or pytest.fail("missing authentication must not call UAPI")
        )),
        min_interval_seconds=1.5,
        sleep=no_wait,
        now=lambda: NOW,
    )
    unauthenticated = await no_auth.fetch_creator("90001", "fallback creator")
    assert unauthenticated.status == CreatorSampleStatus.FAILED
    assert unauthenticated.missing_reason == "uapi_authentication_missing"
    assert unauthenticated.request_audit.final_classification == "authentication_missing"
    assert no_auth_requests == []


@pytest.mark.asyncio
async def test_uapi_creator_provider_honors_retry_after_and_does_not_retry_ordinary_4xx():
    archives_attempts = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal archives_attempts
        if request.url.path.endswith("/archives"):
            archives_attempts += 1
            if request.url.params["mid"] == "40100":
                return httpx.Response(401, json={"code": "UNAUTHENTICATED"}, request=request)
            if request.url.params["mid"] == "40000":
                return httpx.Response(400, json={"code": "INVALID_ARGUMENT"}, request=request)
            if archives_attempts == 1:
                return httpx.Response(429, headers={"Retry-After": "2"}, request=request)
            return httpx.Response(200, json=uapi_archives_payload(1), request=request)
        return httpx.Response(200, json=uapi_userinfo_payload(), request=request)

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    provider = UAPIDevelopmentCreatorProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=2,
        min_interval_seconds=1.5,
        sleep=fake_sleep,
        now=lambda: NOW,
    )
    sample = await provider.fetch_creator("90001", "fallback creator")
    assert sample.status == CreatorSampleStatus.SUCCESS
    assert [attempt.classification for attempt in sample.request_audit.attempts] == [
        "http_429", "success", "success"
    ]
    assert sample.request_audit.total_backoff_seconds == pytest.approx(2.0)
    assert sum(sleeps) >= 2.0

    bad_request = await provider.fetch_creator("40000", "fallback creator")
    assert bad_request.status == CreatorSampleStatus.FAILED
    assert bad_request.request_audit.retry_count == 0
    assert bad_request.request_audit.attempts[0].classification == "http_error"

    authentication_error = await provider.fetch_creator("40100", "fallback creator")
    assert authentication_error.status == CreatorSampleStatus.FAILED
    assert authentication_error.request_audit.retry_count == 0
    assert authentication_error.request_audit.final_classification == "authentication_error"


@pytest.mark.parametrize(
    ("failure_kind", "expected_status", "expected_classification"),
    [
        ("timeout", CreatorSampleStatus.TIMEOUT, "timeout"),
        ("connection", CreatorSampleStatus.FAILED, "connection_error"),
        ("5xx", CreatorSampleStatus.FAILED, "http_5xx"),
    ],
)
@pytest.mark.asyncio
async def test_uapi_creator_provider_bounds_transient_retries(
    failure_kind,
    expected_status,
    expected_classification,
):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if failure_kind == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if failure_kind == "connection":
            raise httpx.ConnectError("fixture connection", request=request)
        return httpx.Response(503, json={"code": "UPSTREAM_ERROR"}, request=request)

    provider = UAPIDevelopmentCreatorProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=2,
        min_interval_seconds=1.5,
        sleep=no_wait,
        now=lambda: NOW,
    )
    sample = await provider.fetch_creator("90001", "fallback creator")
    assert sample.status == expected_status
    assert sample.request_audit.final_classification == expected_classification
    assert sample.request_audit.retry_count == 2
    assert attempts == 3


@pytest.mark.asyncio
async def test_uapi_creator_provider_cancellation_and_interval_floor():
    with pytest.raises(ValueError, match="at least 1.5 seconds"):
        UAPIDevelopmentCreatorProvider(api_key="test-key", min_interval_seconds=1.49)
    provider = UAPIDevelopmentCreatorProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("cancelled call"))),
        min_interval_seconds=1.5,
        sleep=no_wait,
        now=lambda: NOW,
    )
    cancelled = await provider.fetch_creator("90001", "fallback creator", cancel_check=_true)
    assert cancelled.status == CreatorSampleStatus.CANCELLED
    assert cancelled.request_audit.attempt_count == 0


@pytest.mark.asyncio
async def test_uapi_creator_provider_serializes_concurrent_creator_requests():
    active = 0
    max_active = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        if request.url.path.endswith("/archives"):
            return httpx.Response(200, json=uapi_archives_payload(1), request=request)
        return httpx.Response(200, json=uapi_userinfo_payload(), request=request)

    provider = UAPIDevelopmentCreatorProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        min_interval_seconds=1.5,
        sleep=no_wait,
        now=lambda: NOW,
    )
    first, second = await asyncio.gather(
        provider.fetch_creator("90001", "first"),
        provider.fetch_creator("90002", "second"),
    )
    assert first.status == CreatorSampleStatus.SUCCESS
    assert second.status == CreatorSampleStatus.SUCCESS
    assert max_active == 1


@pytest.mark.asyncio
async def test_development_creator_provider_retries_only_transient_failures_and_audits_backoff():
    requests = []
    upload_attempts = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal upload_attempts
        requests.append(request)
        assert "cookie" not in request.headers
        if request.url.path.endswith("/nav"):
            return httpx.Response(200, json=nav_payload(), request=request)
        if request.url.path.endswith("/arc/search"):
            upload_attempts += 1
            if upload_attempts < 3:
                return httpx.Response(503, text="unavailable", request=request)
            return httpx.Response(
                200,
                json={"code": 0, "data": {"is_risk": False, "list": {"vlist": [upload_item(1, days=1)]}}},
                request=request,
            )
        return httpx.Response(200, json={"code": 0, "data": {"follower": 20000}}, request=request)

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    provider = BilibiliDevelopmentCreatorProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=2,
        backoff_base_seconds=0.2,
        min_interval_seconds=0,
        sleep=fake_sleep,
        now=lambda: NOW,
    )
    sample = await provider.fetch_creator("90001", "sanitized creator")
    assert sample.status == CreatorSampleStatus.SUCCESS
    assert upload_attempts == 3
    assert sample.request_audit.attempt_count == 5
    assert sample.request_audit.retry_count == 2
    assert sample.request_audit.total_backoff_seconds == pytest.approx(0.6)
    assert sum(sleeps) == pytest.approx(0.6)
    assert [
        attempt.classification
        for attempt in sample.request_audit.attempts
        if attempt.operation == "uploads"
    ] == ["http_5xx", "http_5xx", "success"]


@pytest.mark.asyncio
async def test_development_creator_provider_risk_control_opens_fixed_circuit_without_dense_retries():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "cookie" not in request.headers
        if request.url.path.endswith("/nav"):
            return httpx.Response(200, json=nav_payload(), request=request)
        if request.url.path.endswith("/arc/search"):
            return httpx.Response(412, text="risk control", request=request)
        raise AssertionError("follower endpoint must not be called after upload risk control")

    provider = BilibiliDevelopmentCreatorProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        min_interval_seconds=0,
        now=lambda: NOW,
    )
    samples = [
        await provider.fetch_creator(str(90001 + index), "sanitized creator")
        for index in range(CREATOR_RISK_CONTROL_THRESHOLD)
    ]
    request_count_at_open = len(requests)
    not_attempted = await provider.fetch_creator("99999", "sanitized creator")
    assert all(sample.status == CreatorSampleStatus.FAILED for sample in samples)
    assert all(sample.request_audit.retry_count == 0 for sample in samples)
    assert samples[-1].request_audit.circuit_state == "opened"
    assert provider.circuit_open
    assert not_attempted.status == CreatorSampleStatus.MISSING
    assert not_attempted.missing_reason == "not_attempted_due_to_risk_control"
    assert not_attempted.request_audit.attempt_count == 0
    assert not_attempted.request_audit.circuit_state == "open"
    assert len(requests) == request_count_at_open == 1 + CREATOR_RISK_CONTROL_THRESHOLD


@pytest.mark.asyncio
async def test_provider_minus_352_is_risk_control_and_success_resets_consecutive_counter():
    upload_outcomes = [-352, 0, -352]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/nav"):
            return httpx.Response(200, json=nav_payload(), request=request)
        if request.url.path.endswith("/arc/search"):
            code = upload_outcomes.pop(0)
            payload = (
                {"code": code, "message": "risk"}
                if code
                else {"code": 0, "data": {"is_risk": False, "list": {"vlist": [upload_item(1, days=1)]}}}
            )
            return httpx.Response(200, json=payload, request=request)
        return httpx.Response(200, json={"code": 0, "data": {"follower": 20000}}, request=request)

    provider = BilibiliDevelopmentCreatorProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        min_interval_seconds=0,
        now=lambda: NOW,
    )
    first = await provider.fetch_creator("90001", "sanitized creator")
    second = await provider.fetch_creator("90002", "sanitized creator")
    third = await provider.fetch_creator("90003", "sanitized creator")
    assert first.missing_reason == "uploads_provider_-352_risk_control"
    assert first.request_audit.retry_count == 0
    assert second.status == CreatorSampleStatus.SUCCESS
    assert second.request_audit.consecutive_risk_control_count == 0
    assert third.request_audit.consecutive_risk_control_count == 1
    assert not provider.circuit_open


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
    payload.update({
        "source_basis": "user_authorized_export",
        "authorization_status": "user_attested",
        "coverage_target_count": 1,
        "coverage_scope_sha256": "0" * 64,
    })
    with pytest.raises(ValidationError, match="coverage hash"):
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


def test_import_creator_provider_validates_neutral_coverage_and_source_authorization():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload.update({
        "source_basis": "user_authorized_export",
        "authorization_status": "user_attested",
        "coverage_target_count": 1,
        "coverage_scope_sha256": creator_scope_hash({"90001"}),
    })
    provider = ImportCreatorProvider.from_json(payload)
    coverage = provider.validate_coverage(
        {"90001"},
        require_exact=True,
        require_source_declared=True,
        require_authorized=True,
    )
    assert coverage.exact_coverage
    assert coverage.authorization_documented
    with pytest.raises(ValueError, match="missing=1, unexpected=1"):
        provider.validate_coverage({"99999"}, require_exact=True)

    uapi_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    uapi_payload.update({
        "source_basis": "third_party_development_api",
        "authorization_status": "development_only",
        "capture_round_id": "sanitized-uapi-round",
        "coverage_target_count": 1,
        "coverage_scope_sha256": creator_scope_hash({"90001"}),
    })
    uapi_import = ImportCreatorProvider.from_json(uapi_payload)
    report = uapi_import.validate_coverage({"90001"}, require_exact=True, require_source_declared=True)
    assert report.source_basis == "third_party_development_api"
    assert report.authorization_status == "development_only"
    assert not report.authorization_documented


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
