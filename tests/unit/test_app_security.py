"""Unit tests for app security bootstrap behavior."""

import pytest
from starlette.middleware.cors import CORSMiddleware

from executec2.config.schema import ExecuteC2Config, ServerConfig
from executec2.server.app import create_app, init_app_state, teardown_app_state


def _config(tmp_path, origins=None):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("fake")
    key.write_text("fake")
    return ExecuteC2Config(
        server=ServerConfig(
            admin_bind_host="127.0.0.1",
            port=4321,
            data_dir=tmp_path / "data",
            tls_cert=cert,
            tls_key=key,
            operator_ui_origins=origins or [],
        ),
        operators={"admin": "secret"},
    )


def test_cors_disabled_by_default(tmp_path):
    app = create_app(_config(tmp_path))
    assert not any(m.cls is CORSMiddleware for m in app.user_middleware)


def test_cors_enabled_with_allowlist(tmp_path):
    app = create_app(_config(tmp_path, origins=["https://ui.example"]))
    assert any(m.cls is CORSMiddleware for m in app.user_middleware)


@pytest.mark.asyncio
async def test_init_requires_master_secret(tmp_path, monkeypatch):
    monkeypatch.delenv("EC2_MASTER_SECRET", raising=False)
    app = create_app(_config(tmp_path))
    with pytest.raises(RuntimeError, match="EC2_MASTER_SECRET"):
        await init_app_state(app, _config(tmp_path))

    # App state is not initialized, but teardown should still be safe if called conditionally.
    if hasattr(app.state, "db"):
        await teardown_app_state(app)


@pytest.mark.asyncio
async def test_tokens_survive_restart_with_same_master_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("EC2_MASTER_SECRET", "restart-secret")
    config = _config(tmp_path)

    app1 = create_app(config)
    await init_app_state(app1, config)
    token = app1.state.jwt_manager.create_access_token("admin", roles=["admin"])
    await teardown_app_state(app1)

    app2 = create_app(config)
    await init_app_state(app2, config)
    claims = app2.state.jwt_manager.verify_token(token, expected_type="access")
    assert claims.username == "admin"
    assert "admin" in claims.roles
    await teardown_app_state(app2)
