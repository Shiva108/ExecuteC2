"""FastAPI application factory for ExecuteC2."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import jwt as pyjwt
import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from executec2.config.schema import ExecuteC2Config
from executec2.server.auth import JWTManager, OTPStore, RateLimiter
from executec2.server.broker import MessageBroker
from executec2.server.database import Database
from executec2.server.events import EventManager
from executec2.server.teamserver import TeamserverCore

logger = logging.getLogger(__name__)


async def init_app_state(app: FastAPI, config: ExecuteC2Config) -> None:
    """Initialize application state. Called by lifespan and directly in tests."""
    data_dir = Path(config.server.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "executec2.db"

    app.state.db = await Database.create(db_path)
    app.state.jwt_manager = JWTManager(
        access_ttl_hours=config.server.access_token_ttl,
        refresh_ttl_hours=config.server.refresh_token_ttl,
    )
    app.state.otp_store = OTPStore()
    app.state.rate_limiter = RateLimiter(max_requests=config.server.auth_rate_limit)
    app.state.operators = config.operators
    app.state.event_manager = EventManager()
    await app.state.event_manager.start()
    broker = MessageBroker()
    await broker.start()
    app.state.broker = broker
    app.state.agents: dict = {}
    app.state.listener_instances: dict = {}

    # Register built-in commands
    from executec2.commands.builtin import register_builtin_commands
    register_builtin_commands()

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


async def teardown_app_state(app: FastAPI) -> None:
    """Shutdown application state. Called by lifespan and directly in tests."""
    if hasattr(app.state, "teamserver") and app.state.teamserver:
        await app.state.teamserver.stop()
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


def _get_current_user(request: Request) -> str:
    """Extract and verify JWT from Authorization header. Returns username."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer", "X-Code": "UNAUTHORIZED"},
        )
    token = auth.removeprefix("Bearer ")
    jwt_manager: JWTManager = request.app.state.jwt_manager
    try:
        claims = jwt_manager.verify_token(token, expected_type="access")
        return claims.username
    except pyjwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer", "X-Code": "UNAUTHORIZED"},
        )


def create_app(config: ExecuteC2Config) -> FastAPI:
    app = FastAPI(
        title="ExecuteC2",
        version="0.1.0",
        lifespan=_make_lifespan(config),
    )

    # Attach the auth helper as app state method
    app.state.get_current_user = _get_current_user

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
    from executec2.server.routes.sync import router as sync_router
    from executec2.server.routes.targets import router as targets_router
    from executec2.server.routes.tasks import router as tasks_router
    from executec2.server.routes.tunnels import router as tunnels_router

    app.include_router(auth_router)
    app.include_router(agents_router)
    app.include_router(listeners_router)
    app.include_router(tasks_router)
    app.include_router(credentials_router)
    app.include_router(targets_router)
    app.include_router(tunnels_router)
    app.include_router(sync_router)
    app.include_router(chat_router)

    return app


async def run_server(config: ExecuteC2Config) -> None:
    app = create_app(config)
    ssl_kwargs = {}
    if config.server.tls_cert and config.server.tls_key:
        ssl_kwargs["ssl_certfile"] = str(config.server.tls_cert)
        ssl_kwargs["ssl_keyfile"] = str(config.server.tls_key)

    uv_config = uvicorn.Config(
        app=app,
        host=config.server.host,
        port=config.server.port,
        log_level=config.logging.level.lower(),
        **ssl_kwargs,
    )
    server = uvicorn.Server(uv_config)
    await server.serve()
