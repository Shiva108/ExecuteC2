"""Traffic profile helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from executec2.server.models import (
    InfraStage,
    TrafficProfileData,
    TrafficProfileKind,
    TrafficProfileTLSMode,
)

_PROFILE_FIELDS = {
    "uris",
    "http_method",
    "user_agents",
    "host_headers",
    "request_headers",
    "response_headers",
    "trust_x_forwarded_for",
    "page_error",
    "page_payload",
}


def normalize_listener_profile_payload(
    *,
    listener_name: str,
    listener_type: str,
    config: dict,
) -> tuple[TrafficProfileData | None, dict]:
    """Split inline traffic-profile fields from listener runtime config."""
    cleaned = dict(config)
    extracted = {key: cleaned.pop(key) for key in list(cleaned.keys()) if key in _PROFILE_FIELDS}
    if not extracted:
        return None, cleaned

    host_headers = list(extracted.get("host_headers", []))
    callback_hostnames = list(cleaned.get("callback_addresses", []))
    now = datetime.now(UTC)
    profile = TrafficProfileData(
        profile_id=f"tp-{uuid4().hex[:12]}",
        name=f"{listener_name}-implicit",
        listener_type=listener_type,
        stage=InfraStage.STAGE_1,
        profile_kind=TrafficProfileKind.IMPLICIT,
        callback_hostnames=callback_hostnames,
        uris=list(extracted.get("uris", [])),
        http_method=str(extracted.get("http_method", "POST")).upper(),
        user_agents=list(extracted.get("user_agents", [])),
        host_headers=host_headers,
        request_headers=dict(extracted.get("request_headers", {})),
        response_headers=dict(extracted.get("response_headers", {})),
        trust_x_forwarded_for=bool(extracted.get("trust_x_forwarded_for", False)),
        page_error=str(extracted.get("page_error", "")),
        page_payload=str(extracted.get("page_payload", "")),
        tls_mode=TrafficProfileTLSMode.OPTIONAL,
        source_listener=listener_name,
        create_time=now,
        update_time=now,
    )
    return profile, cleaned


def merge_listener_config_with_profile(config: dict, profile: TrafficProfileData | None) -> dict:
    """Overlay resolved traffic-profile fields onto runtime listener config."""
    merged = dict(config)
    if profile is None:
        return merged
    merged["uris"] = list(profile.uris)
    merged["http_method"] = profile.http_method
    merged["user_agents"] = list(profile.user_agents)
    merged["host_headers"] = list(profile.host_headers)
    merged["request_headers"] = dict(profile.request_headers)
    merged["response_headers"] = dict(profile.response_headers)
    merged["trust_x_forwarded_for"] = profile.trust_x_forwarded_for
    if profile.page_error:
        merged["page_error"] = profile.page_error
    if profile.page_payload:
        merged["page_payload"] = profile.page_payload
    return merged
