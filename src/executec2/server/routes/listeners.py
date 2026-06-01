"""Listener routes — Phase 6 implementation."""

import msgpack
from fastapi import APIRouter, Depends, HTTPException, Request, status

from executec2.infrastructure.compat import IncompatibleProfileError, validate_profile_compatibility
from executec2.infrastructure.profiles import (
    merge_listener_config_with_profile,
    normalize_listener_profile_payload,
)
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
    ListenerData,
    ListenerStatus,
    SyncPacketType,
    TokenClaims,
)

router = APIRouter(prefix="/api/listeners", tags=["listeners"])


def _get_listener_instances(request: Request) -> dict:
    """Return the in-memory listener instances dict from app state."""
    if not hasattr(request.app.state, "listener_instances"):
        request.app.state.listener_instances = {}
    return request.app.state.listener_instances


@router.get("")
async def list_listeners(
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    listeners = await db.listener_list()
    return [listener.model_dump(mode="json") for listener in listeners]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_listener(
    body: dict,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    """Create and start a new listener."""
    enforce_limit(request, "listener_mutation", limit_key_user_ip(request, claims.username))
    from executec2.listeners import get_listener_class

    listener_type = body.get("listener_type")
    listener_name = body.get("listener_name")
    config = body.get("config", {})
    traffic_profile_id = body.get("traffic_profile_id", "")
    ingress_asset_id = body.get("ingress_asset_id", "")

    if not listener_type or not listener_name:
        raise HTTPException(status_code=400, detail="listener_type and listener_name required")

    cls = get_listener_class(listener_type)
    if cls is None:
        raise HTTPException(status_code=400, detail=f"Unknown listener type: {listener_type}")

    db = request.app.state.db
    if await db.listener_get(listener_name) is not None:
        raise HTTPException(status_code=409, detail="Listener name already exists")

    profile = None
    if traffic_profile_id:
        profile = await db.traffic_profile_get(traffic_profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Traffic profile not found")
    else:
        profile, config = normalize_listener_profile_payload(
            listener_name=listener_name,
            listener_type=listener_type,
            config=config,
        )
        if profile is not None:
            await db.traffic_profile_insert(profile)
            traffic_profile_id = profile.profile_id

    resolved_config = merge_listener_config_with_profile(config, profile)

    if ingress_asset_id and profile is not None:
        chain = await request.app.state.infrastructure.get_asset_chain(ingress_asset_id)
        try:
            validate_profile_compatibility(
                profile,
                chain,
                port_bind=int(resolved_config.get("port_bind", 0)),
            )
        except IncompatibleProfileError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    plugin = cls()
    try:
        validated = plugin.validate_config(dict(resolved_config))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Build teamserver interface from app state
    teamserver = _build_teamserver_interface(request)
    validated["listener_name"] = listener_name

    try:
        await plugin.start(validated, teamserver)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start listener: {e}")

    instances = _get_listener_instances(request)
    instances[listener_name] = plugin

    data = ListenerData(
        listener_name=listener_name,
        listener_type=listener_type,
        config=validated,
        traffic_profile_id=traffic_profile_id,
        ingress_asset_id=ingress_asset_id,
        status=ListenerStatus.RUNNING,
    )
    await db.listener_insert(data)

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(
        BrokerMessage(
            msg_type=BrokerMsgType.EVENT,
            packet_type=SyncPacketType.LISTENER_START,
            data=msgpack.packb(data.model_dump(mode="json")),
            category="listeners",
        )
    )

    event_manager = request.app.state.event_manager
    await event_manager.emit_async("listener.start", {"listener_name": listener_name})

    return data.model_dump(mode="json")


@router.put("/{listener_name}")
async def update_listener(
    listener_name: str,
    body: dict,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    """Update listener config (stop + restart with new config)."""
    enforce_limit(request, "listener_mutation", limit_key_user_ip(request, claims.username))
    db = request.app.state.db
    existing = await db.listener_get(listener_name)
    if existing is None:
        raise HTTPException(status_code=404, detail="Listener not found")

    instances = _get_listener_instances(request)
    plugin = instances.get(listener_name)

    new_config = body.get("config", existing.config)
    traffic_profile_id = body.get("traffic_profile_id", existing.traffic_profile_id)
    ingress_asset_id = body.get("ingress_asset_id", existing.ingress_asset_id)
    profile = None
    if traffic_profile_id:
        profile = await db.traffic_profile_get(traffic_profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Traffic profile not found")
    else:
        maybe_profile, new_config = normalize_listener_profile_payload(
            listener_name=listener_name,
            listener_type=existing.listener_type,
            config=new_config,
        )
        if maybe_profile is not None:
            if existing.traffic_profile_id:
                current = await db.traffic_profile_get(existing.traffic_profile_id)
                if current and current.profile_kind.value == "implicit":
                    maybe_profile.profile_id = current.profile_id
                    maybe_profile.create_time = current.create_time
                    await db.traffic_profile_update(
                        current.profile_id, **maybe_profile.model_dump(mode="python")
                    )
                    traffic_profile_id = current.profile_id
                else:
                    await db.traffic_profile_insert(maybe_profile)
                    traffic_profile_id = maybe_profile.profile_id
            else:
                await db.traffic_profile_insert(maybe_profile)
                traffic_profile_id = maybe_profile.profile_id
            profile = maybe_profile

    resolved_config = merge_listener_config_with_profile(new_config, profile)
    if ingress_asset_id and profile is not None:
        chain = await request.app.state.infrastructure.get_asset_chain(ingress_asset_id)
        try:
            validate_profile_compatibility(
                profile,
                chain,
                port_bind=int(resolved_config.get("port_bind", 0)),
            )
        except IncompatibleProfileError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    if plugin is not None:
        try:
            resolved_config = plugin.validate_config(dict(resolved_config))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    await db.listener_update(
        listener_name,
        config=resolved_config,
        traffic_profile_id=traffic_profile_id,
        ingress_asset_id=ingress_asset_id,
    )

    broker: MessageBroker = request.app.state.broker
    updated = existing.model_copy(
        update={
            "config": resolved_config,
            "traffic_profile_id": traffic_profile_id,
            "ingress_asset_id": ingress_asset_id,
        }
    )
    await broker.broadcast(
        BrokerMessage(
            msg_type=BrokerMsgType.EVENT,
            packet_type=SyncPacketType.LISTENER_EDIT,
            data=msgpack.packb(updated.model_dump(mode="json")),
            category="listeners",
        )
    )

    return updated.model_dump(mode="json")


@router.post("/{listener_name}/stop", status_code=status.HTTP_204_NO_CONTENT)
async def stop_listener(
    listener_name: str,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "listener_mutation", limit_key_user_ip(request, claims.username))
    db = request.app.state.db
    if await db.listener_get(listener_name) is None:
        raise HTTPException(status_code=404, detail="Listener not found")

    instances = _get_listener_instances(request)
    plugin = instances.pop(listener_name, None)
    if plugin is not None:
        try:
            await plugin.stop()
        except Exception:
            pass

    await db.listener_update(listener_name, status=str(ListenerStatus.STOPPED))

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(
        BrokerMessage(
            msg_type=BrokerMsgType.EVENT,
            packet_type=SyncPacketType.LISTENER_STOP,
            data=msgpack.packb({"listener_name": listener_name}),
            category="listeners",
        )
    )

    event_manager = request.app.state.event_manager
    await event_manager.emit_async("listener.stop", {"listener_name": listener_name})


@router.post("/{listener_name}/pause", status_code=status.HTTP_204_NO_CONTENT)
async def pause_listener(
    listener_name: str,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "listener_mutation", limit_key_user_ip(request, claims.username))
    db = request.app.state.db
    if await db.listener_get(listener_name) is None:
        raise HTTPException(status_code=404, detail="Listener not found")

    instances = _get_listener_instances(request)
    plugin = instances.get(listener_name)
    if plugin is not None:
        await plugin.pause()

    await db.listener_update(listener_name, status=str(ListenerStatus.PAUSED))


@router.post("/{listener_name}/resume", status_code=status.HTTP_204_NO_CONTENT)
async def resume_listener(
    listener_name: str,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "listener_mutation", limit_key_user_ip(request, claims.username))
    db = request.app.state.db
    if await db.listener_get(listener_name) is None:
        raise HTTPException(status_code=404, detail="Listener not found")

    instances = _get_listener_instances(request)
    plugin = instances.get(listener_name)
    if plugin is not None:
        await plugin.resume()

    await db.listener_update(listener_name, status=str(ListenerStatus.RUNNING))


def _build_teamserver_interface(request: Request):
    """Build a minimal TeamserverInterface from app state for use by listener plugins."""
    from executec2.server.teamserver import TeamserverCore

    if hasattr(request.app.state, "teamserver"):
        return request.app.state.teamserver

    # Lazy-initialize TeamserverCore if not already done
    core = TeamserverCore(
        db=request.app.state.db,
        broker=request.app.state.broker,
        event_manager=request.app.state.event_manager,
        agents=request.app.state.agents,
    )
    request.app.state.teamserver = core
    return core
