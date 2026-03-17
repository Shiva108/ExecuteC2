"""Integration tests for auth endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from executec2.config.schema import ExecuteC2Config, ServerConfig
from executec2.server.app import create_app, init_app_state, teardown_app_state


def make_config(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("fake")
    key.write_text("fake")
    return ExecuteC2Config(
        server=ServerConfig(
            host="127.0.0.1",
            port=4321,
            data_dir=tmp_path / "data",
            tls_cert=cert,
            tls_key=key,
        ),
        operators={"admin": "password123"},
    )


@pytest.fixture
async def client(tmp_path):
    config = make_config(tmp_path)
    app = create_app(config)
    await init_app_state(app, config)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        await teardown_app_state(app)


async def test_login_success(client):
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


async def test_login_wrong_password(client):
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


async def test_login_unknown_user(client):
    resp = await client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


async def test_rate_limit(client):
    """After 10 attempts, 11th returns 429."""
    for _ in range(10):
        await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 429


async def test_refresh_tokens(client):
    login = await client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    refresh_token = login.json()["refresh_token"]

    resp = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data


async def test_refresh_with_access_token_fails(client):
    login = await client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    access_token = login.json()["access_token"]

    resp = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 401


async def test_protected_route_requires_auth(client):
    resp = await client.get("/api/agents")
    assert resp.status_code == 401


async def test_protected_route_with_valid_token(client):
    login = await client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    token = login.json()["access_token"]

    resp = await client.get("/api/agents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_otp_generation(client):
    login = await client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    token = login.json()["access_token"]

    resp = await client.post(
        "/api/auth/otp",
        json={"type": "connect"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert "otp" in resp.json()
    assert len(resp.json()["otp"]) == 32


async def test_all_routes_registered(client):
    """Smoke test: all API endpoints exist (200, 401, 501, etc — not 404)."""
    login = await client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    routes = [
        ("GET", "/api/listeners"),
        ("GET", "/api/agents"),
        ("GET", "/api/credentials"),
        ("GET", "/api/targets"),
        ("GET", "/api/tunnels"),
    ]
    for method, path in routes:
        resp = await client.request(method, path, headers=headers)
        assert resp.status_code != 404, f"{method} {path} returned 404"
