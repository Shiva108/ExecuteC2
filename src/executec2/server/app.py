"""FastAPI application factory for ExecuteC2."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from executec2.config.schema import ExecuteC2Config
from executec2.server.auth import JWTManager, OTPStore, RateLimiter
from executec2.server.broker import MessageBroker
from executec2.server.database import Database
from executec2.server.events import EventManager
from executec2.server.session_manager import SessionManager
from executec2.server.secrets import SecretContext
from executec2.server.teamserver import TeamserverCore
from executec2.infrastructure.service import InfrastructureService
from executec2.tunnels import TunnelManager

logger = logging.getLogger(__name__)


async def init_app_state(app: FastAPI, config: ExecuteC2Config) -> None:
    """Initialize application state. Called by lifespan and directly in tests."""
    master_secret = os.environ.get("EC2_MASTER_SECRET")
    if not master_secret:
        raise RuntimeError("EC2_MASTER_SECRET is required")

    app.state.secret_context = SecretContext.from_master_secret(master_secret)

    data_dir = Path(config.server.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "executec2.db"

    app.state.db = await Database.create(
        db_path,
        secret_context=app.state.secret_context,
    )
    await app.state.db.migrate_secrets()
    app.state.jwt_manager = JWTManager(
        secret=app.state.secret_context.jwt_signing_key,
        access_ttl_hours=config.server.access_token_ttl,
        refresh_ttl_hours=config.server.refresh_token_ttl,
    )
    app.state.otp_store = OTPStore()
    app.state.rate_limiter = RateLimiter(max_requests=config.server.auth_rate_limit)
    app.state.route_limiters = {
        "otp": RateLimiter(max_requests=30),
        "command": RateLimiter(max_requests=120),
        "raw_command": RateLimiter(max_requests=10),
        "listener_mutation": RateLimiter(max_requests=10),
        "tunnel_mutation": RateLimiter(max_requests=10),
        "profile_mutation": RateLimiter(max_requests=20),
        "infrastructure_mutation": RateLimiter(max_requests=20),
        "deployment_mutation": RateLimiter(max_requests=20),
    }
    app.state.max_task_payload_bytes = config.server.max_task_payload_bytes
    app.state.operators = {
        username: {
            "password": op.password,
            "roles": list(op.roles) if op.roles else ["operator"],
        }
        for username, op in config.operators.items()
    }
    app.state.event_manager = EventManager()
    await app.state.event_manager.start()
    broker = MessageBroker()
    await broker.start()
    app.state.broker = broker
    app.state.agents: dict = {}
    app.state.listener_instances: dict = {}
    app.state.infrastructure = InfrastructureService(app.state.db, data_dir)

    # Register built-in commands
    from executec2.commands.builtin import register_builtin_commands
    from executec2.agents import load_agents
    from executec2.listeners import load_listeners
    register_builtin_commands()
    load_listeners(
        list(
            dict.fromkeys(
                config.plugins.listeners
                + [
                    "executec2.listeners.http_listener",
                    "executec2.listeners.websocket_listener",
                ]
            )
        )
    )
    load_agents(list(dict.fromkeys(config.plugins.agents + ["executec2.agents.python_agent"])))

    # Initialize teamserver core and register default agent plugins
    from executec2.agents.python_agent import PythonAgentPlugin
    teamserver = TeamserverCore(
        db=app.state.db,
        broker=broker,
        event_manager=app.state.event_manager,
        agents=app.state.agents,
    )
    teamserver.register_agent_plugin("python", PythonAgentPlugin())
    await teamserver.start()
    app.state.teamserver = teamserver
    app.state.session_manager = SessionManager(
        app.state.db,
        broker,
        app.state.event_manager,
        app.state.agents,
    )
    teamserver.session_manager = app.state.session_manager
    app.state.tunnel_manager = TunnelManager(app.state.session_manager)


async def teardown_app_state(app: FastAPI) -> None:
    """Shutdown application state. Called by lifespan and directly in tests."""
    if hasattr(app.state, "teamserver") and app.state.teamserver:
        await app.state.teamserver.stop()
    if hasattr(app.state, "tunnel_manager") and app.state.tunnel_manager:
        await app.state.tunnel_manager.stop_all()
    if app.state.broker:
        await app.state.broker.stop()
    await app.state.event_manager.stop()
    await app.state.db.close()


def _make_lifespan(config: ExecuteC2Config):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_app_state(app, config)
        logger.info("ExecuteC2 started")
        yield
        await teardown_app_state(app)
        logger.info("ExecuteC2 stopped")

    return lifespan

def create_app(config: ExecuteC2Config) -> FastAPI:
    app = FastAPI(
        title="ExecuteC2",
        version="0.1.0",
        lifespan=_make_lifespan(config),
    )
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
        name="static",
    )

    if config.server.operator_ui_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.server.operator_ui_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        code = exc.headers.get("X-Code", "ERROR") if exc.headers else "ERROR"
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": code},
        )

    from executec2.server.routes.agents import router as agents_router
    from executec2.server.routes.auth import router as auth_router
    from executec2.server.routes.chat import router as chat_router
    from executec2.server.routes.credentials import router as credentials_router
    from executec2.server.routes.listeners import router as listeners_router
    from executec2.server.routes.infrastructure import router as infrastructure_router
    from executec2.server.routes.sync import router as sync_router
    from executec2.server.routes.sessions import router as sessions_router
    from executec2.server.routes.targets import router as targets_router
    from executec2.server.routes.tasks import router as tasks_router
    from executec2.server.routes.traffic_profiles import router as traffic_profiles_router
    from executec2.server.routes.tunnels import router as tunnels_router
    from executec2.server.routes.ui import router as ui_router

    app.include_router(auth_router)
    app.include_router(agents_router)
    app.include_router(listeners_router)
    app.include_router(traffic_profiles_router)
    app.include_router(infrastructure_router)
    app.include_router(tasks_router)
    app.include_router(credentials_router)
    app.include_router(targets_router)
    app.include_router(tunnels_router)
    app.include_router(sync_router)
    app.include_router(sessions_router)
    app.include_router(chat_router)
    app.include_router(ui_router)

    return app


async def run_server(config: ExecuteC2Config) -> None:
    app = create_app(config)
    ssl_kwargs = {}
    if config.server.tls_cert and config.server.tls_key:
        ssl_kwargs["ssl_certfile"] = str(config.server.tls_cert)
        ssl_kwargs["ssl_keyfile"] = str(config.server.tls_key)

    uv_config = uvicorn.Config(
        app=app,
        host=config.server.admin_bind_host or config.server.host,
        port=config.server.port,
        log_level=config.logging.level.lower(),
        **ssl_kwargs,
    )
    server = uvicorn.Server(uv_config)
    await server.serve()
