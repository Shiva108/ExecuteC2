"""Infrastructure inventory and orchestration routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import msgpack
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from executec2.infrastructure.compat import IncompatibleProfileError
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
    DeploymentRunStatus,
    DeployTarget,
    InfraHealthStatus,
    InfraStage,
    InfrastructureAssetData,
    InfrastructureAssetType,
    SyncPacketType,
    TokenClaims,
)

router = APIRouter(prefix="/api/infrastructure", tags=["infrastructure"])


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _asset_from_body(
    body: dict, *, existing: InfrastructureAssetData | None = None
) -> InfrastructureAssetData:
    now = datetime.now(UTC)
    default_type = existing.asset_type.value if existing else body.get("asset_type")
    expires_at = body.get(
        "certificate_expires_at",
        existing.certificate_expires_at.isoformat()
        if existing and existing.certificate_expires_at
        else None,
    )
    last_health = body.get(
        "last_health_observed_at",
        existing.last_health_observed_at.isoformat()
        if existing and existing.last_health_observed_at
        else None,
    )
    return InfrastructureAssetData(
        asset_id=body.get("asset_id", existing.asset_id if existing else uuid4().hex),
        name=body["name"] if "name" in body else existing.name,
        asset_type=InfrastructureAssetType(default_type),
        stage=InfraStage(body.get("stage", int(existing.stage) if existing else 1)),
        provider=str(body.get("provider", existing.provider if existing else "")),
        parent_asset_id=str(
            body.get("parent_asset_id", existing.parent_asset_id if existing else "")
        ),
        linked_listener_name=str(
            body.get("linked_listener_name", existing.linked_listener_name if existing else "")
        ),
        traffic_profile_id=str(
            body.get("traffic_profile_id", existing.traffic_profile_id if existing else "")
        ),
        owner=str(body.get("owner", existing.owner if existing else "")),
        tags=list(body.get("tags", existing.tags if existing else [])),
        config=dict(body.get("config", existing.config if existing else {})),
        deploy_target=DeployTarget(
            body.get(
                "deploy_target", existing.deploy_target.value if existing else "docker_compose"
            )
        ),
        health=InfraHealthStatus(
            body.get("health", existing.health.value if existing else "unknown")
        ),
        dns_state=str(body.get("dns_state", existing.dns_state if existing else "")),
        certificate_expires_at=_parse_optional_datetime(expires_at),
        upstream_asset_ids=list(
            body.get("upstream_asset_ids", existing.upstream_asset_ids if existing else [])
        ),
        downstream_asset_ids=list(
            body.get("downstream_asset_ids", existing.downstream_asset_ids if existing else [])
        ),
        stage_owner=str(body.get("stage_owner", existing.stage_owner if existing else "")),
        rendered_checksum=str(
            body.get("rendered_checksum", existing.rendered_checksum if existing else "")
        ),
        last_deployment_run_id=str(
            body.get(
                "last_deployment_run_id",
                existing.last_deployment_run_id if existing else "",
            )
        ),
        last_health_observed_at=_parse_optional_datetime(last_health),
        create_time=existing.create_time if existing else now,
        update_time=now,
    )


async def _broadcast_asset(request: Request, packet_type: SyncPacketType, payload: dict) -> None:
    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(
        BrokerMessage(
            msg_type=BrokerMsgType.EVENT,
            packet_type=packet_type,
            data=msgpack.packb(payload),
            category="infrastructure",
        )
    )


async def _broadcast_run(request: Request, packet_type: SyncPacketType, payload: dict) -> None:
    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(
        BrokerMessage(
            msg_type=BrokerMsgType.EVENT,
            packet_type=packet_type,
            data=msgpack.packb(payload),
            category="deployment_runs",
        )
    )


@router.get("/assets")
async def list_assets(
    request: Request,
    stage: int | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    stage_enum = InfraStage(stage) if stage is not None else None
    type_enum = InfrastructureAssetType(asset_type) if asset_type else None
    assets = await request.app.state.db.infrastructure_asset_list(
        stage=stage_enum, asset_type=type_enum
    )
    return [asset.model_dump(mode="json") for asset in assets]


@router.get("/assets/{asset_id}")
async def get_asset(
    asset_id: str,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    asset = await request.app.state.db.infrastructure_asset_get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Infrastructure asset not found")
    return asset.model_dump(mode="json")


@router.post("/assets", status_code=status.HTTP_201_CREATED)
async def create_asset(
    body: dict,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "infrastructure_mutation", limit_key_user_ip(request, claims.username))
    if "name" not in body or "asset_type" not in body or "stage" not in body:
        raise HTTPException(status_code=400, detail="name, asset_type, and stage required")
    asset = _asset_from_body(body)
    await request.app.state.db.infrastructure_asset_insert(asset)
    await _broadcast_asset(
        request, SyncPacketType.INFRA_ASSET_CREATE, asset.model_dump(mode="json")
    )
    return asset.model_dump(mode="json")


@router.put("/assets/{asset_id}")
async def update_asset(
    asset_id: str,
    body: dict,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "infrastructure_mutation", limit_key_user_ip(request, claims.username))
    existing = await request.app.state.db.infrastructure_asset_get(asset_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Infrastructure asset not found")
    asset = _asset_from_body(body, existing=existing)
    await request.app.state.db.infrastructure_asset_update(
        asset_id, **asset.model_dump(mode="python")
    )
    await _broadcast_asset(
        request, SyncPacketType.INFRA_ASSET_UPDATE, asset.model_dump(mode="json")
    )
    return asset.model_dump(mode="json")


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: str,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "infrastructure_mutation", limit_key_user_ip(request, claims.username))
    if await request.app.state.db.infrastructure_asset_get(asset_id) is None:
        raise HTTPException(status_code=404, detail="Infrastructure asset not found")
    await request.app.state.db.infrastructure_asset_delete(asset_id)
    await _broadcast_asset(request, SyncPacketType.INFRA_ASSET_DELETE, {"asset_id": asset_id})


@router.get("/views/stages/{stage}")
async def stage_view(
    stage: int,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    return await request.app.state.infrastructure.build_stage_view(InfraStage(stage))


@router.get("/views/ingress-chains/{asset_id}")
async def ingress_chain_view(
    asset_id: str,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    return await request.app.state.infrastructure.build_ingress_chain_view(asset_id)


@router.get("/views/drift-health")
async def drift_health_view(
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    return await request.app.state.infrastructure.build_drift_health_summary()


@router.get("/runs")
async def list_runs(
    request: Request,
    asset_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    operation: str | None = Query(default=None),
    target: str | None = Query(default=None),
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    try:
        run_status = DeploymentRunStatus(status_filter) if status_filter else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run status")
    try:
        target_value = DeployTarget(target) if target else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid deploy target")
    runs = await request.app.state.db.deployment_run_list(
        asset_id=asset_id,
        status=run_status,
        operation=operation,
        target=target_value,
    )
    return [run.model_dump(mode="json") for run in runs]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    run = await request.app.state.db.deployment_run_get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Deployment run not found")
    return run.model_dump(mode="json")


@router.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_run(
    body: dict,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "deployment_mutation", limit_key_user_ip(request, claims.username))
    asset_id = body.get("asset_id", "")
    operation = str(body.get("operation", ""))
    if not asset_id or not operation or "target" not in body:
        raise HTTPException(status_code=400, detail="asset_id, operation, and target required")
    if operation not in {"apply", "reapply", "rotate", "teardown"}:
        raise HTTPException(status_code=400, detail="Unsupported operation")
    try:
        target = DeployTarget(body["target"])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid deploy target")
    try:
        run = await request.app.state.infrastructure.create_plan(
            asset_id=asset_id,
            operation=operation,
            target=target,
            created_by=claims.username,
        )
    except IncompatibleProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        if str(exc) == "Asset not found":
            raise HTTPException(status_code=404, detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    await _broadcast_run(request, SyncPacketType.DEPLOYMENT_RUN_CREATE, run.model_dump(mode="json"))
    return run.model_dump(mode="json")


@router.post("/runs/{run_id}/apply")
async def apply_run(
    run_id: str,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "deployment_mutation", limit_key_user_ip(request, claims.username))
    try:
        run = await request.app.state.infrastructure.apply_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await _broadcast_run(request, SyncPacketType.DEPLOYMENT_RUN_UPDATE, run.model_dump(mode="json"))
    return run.model_dump(mode="json")
