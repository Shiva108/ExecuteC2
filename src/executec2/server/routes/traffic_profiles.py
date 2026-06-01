"""Traffic profile API routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import msgpack
from fastapi import APIRouter, Depends, HTTPException, Request, status

from executec2.server.auth import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    enforce_limit,
    limit_key_user_ip,
    require_roles,
)
from executec2.server.broker import MessageBroker
from executec2.server.models import (
    BrokerMessage,
    BrokerMsgType,
    InfraStage,
    SyncPacketType,
    TokenClaims,
    TrafficProfileData,
    TrafficProfileKind,
    TrafficProfileTLSMode,
)

router = APIRouter(prefix="/api/traffic-profiles", tags=["traffic-profiles"])


def _profile_from_body(
    body: dict, *, existing: TrafficProfileData | None = None
) -> TrafficProfileData:
    now = datetime.now(UTC)
    return TrafficProfileData(
        profile_id=body.get(
            "profile_id", existing.profile_id if existing else f"tp-{uuid4().hex[:12]}"
        ),
        name=body["name"] if "name" in body else existing.name,
        listener_type=body.get("listener_type", existing.listener_type if existing else "http"),
        stage=InfraStage(body.get("stage", int(existing.stage) if existing else 1)),
        profile_kind=TrafficProfileKind(
            body.get("profile_kind", existing.profile_kind.value if existing else "explicit")
        ),
        callback_hostnames=list(
            body.get("callback_hostnames", existing.callback_hostnames if existing else [])
        ),
        uris=list(body.get("uris", existing.uris if existing else [])),
        http_method=str(
            body.get("http_method", existing.http_method if existing else "POST")
        ).upper(),
        user_agents=list(body.get("user_agents", existing.user_agents if existing else [])),
        host_headers=list(body.get("host_headers", existing.host_headers if existing else [])),
        request_headers=dict(
            body.get("request_headers", existing.request_headers if existing else {})
        ),
        response_headers=dict(
            body.get("response_headers", existing.response_headers if existing else {})
        ),
        trust_x_forwarded_for=bool(
            body.get(
                "trust_x_forwarded_for",
                existing.trust_x_forwarded_for if existing else False,
            )
        ),
        page_error=str(body.get("page_error", existing.page_error if existing else "")),
        page_payload=str(body.get("page_payload", existing.page_payload if existing else "")),
        tls_mode=TrafficProfileTLSMode(
            body.get("tls_mode", existing.tls_mode.value if existing else "optional")
        ),
        source_listener=str(
            body.get("source_listener", existing.source_listener if existing else "")
        ),
        create_time=existing.create_time if existing else now,
        update_time=now,
    )


@router.get("")
async def list_traffic_profiles(
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    profiles = await request.app.state.db.traffic_profile_list()
    return [profile.model_dump(mode="json") for profile in profiles]


@router.get("/{profile_id}")
async def get_traffic_profile(
    profile_id: str,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    profile = await request.app.state.db.traffic_profile_get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Traffic profile not found")
    return profile.model_dump(mode="json")


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_traffic_profile(
    body: dict,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "profile_mutation", limit_key_user_ip(request, claims.username))
    if "name" not in body:
        raise HTTPException(status_code=400, detail="name required")
    profile = _profile_from_body(body)
    await request.app.state.db.traffic_profile_insert(profile)
    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(
        BrokerMessage(
            msg_type=BrokerMsgType.EVENT,
            packet_type=SyncPacketType.TRAFFIC_PROFILE_CREATE,
            data=msgpack.packb(profile.model_dump(mode="json")),
            category="traffic_profiles",
        )
    )
    return profile.model_dump(mode="json")


@router.put("/{profile_id}")
async def update_traffic_profile(
    profile_id: str,
    body: dict,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "profile_mutation", limit_key_user_ip(request, claims.username))
    existing = await request.app.state.db.traffic_profile_get(profile_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Traffic profile not found")
    profile = _profile_from_body(body, existing=existing)
    await request.app.state.db.traffic_profile_update(
        profile_id, **profile.model_dump(mode="python")
    )
    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(
        BrokerMessage(
            msg_type=BrokerMsgType.EVENT,
            packet_type=SyncPacketType.TRAFFIC_PROFILE_UPDATE,
            data=msgpack.packb(profile.model_dump(mode="json")),
            category="traffic_profiles",
        )
    )
    return profile.model_dump(mode="json")


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_traffic_profile(
    profile_id: str,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "profile_mutation", limit_key_user_ip(request, claims.username))
    if await request.app.state.db.traffic_profile_get(profile_id) is None:
        raise HTTPException(status_code=404, detail="Traffic profile not found")
    await request.app.state.db.traffic_profile_delete(profile_id)
    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(
        BrokerMessage(
            msg_type=BrokerMsgType.EVENT,
            packet_type=SyncPacketType.TRAFFIC_PROFILE_DELETE,
            data=msgpack.packb({"profile_id": profile_id}),
            category="traffic_profiles",
        )
    )
