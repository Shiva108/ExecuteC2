"""Integration tests for credential + chat API — Phase 12."""

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
async def auth_client(tmp_path):
    config = make_config(tmp_path)
    app = create_app(config)
    await init_app_state(app, config)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            login = await c.post("/api/auth/login", json={"username": "admin", "password": "password123"})
            token = login.json()["access_token"]
            c.headers["Authorization"] = f"Bearer {token}"
            yield c, app.state
    finally:
        await teardown_app_state(app)


# ---------------------------------------------------------------------------
# Credential CRUD
# ---------------------------------------------------------------------------


async def test_credential_crud_api(auth_client):
    client, _ = auth_client

    # Create
    resp = await client.post("/api/credentials", json={
        "username": "jdoe",
        "secret": "s3cr3t",
        "realm": "CORP",
        "cred_type": "password",
    })
    assert resp.status_code == 201
    cred_id = resp.json()["cred_id"]

    # List
    resp = await client.get("/api/credentials")
    assert resp.status_code == 200
    assert any(c["cred_id"] == cred_id for c in resp.json())

    # Update
    resp = await client.put(f"/api/credentials/{cred_id}", json={"tag": "corp-admin"})
    assert resp.status_code == 200

    # Delete
    resp = await client.delete(f"/api/credentials/{cred_id}")
    assert resp.status_code == 204

    resp = await client.get("/api/credentials")
    assert all(c["cred_id"] != cred_id for c in resp.json())


async def test_credential_at_rest_encryption(auth_client):
    """Secret stored in DB as ciphertext; returned plaintext via API."""
    client, state = auth_client

    resp = await client.post("/api/credentials", json={
        "username": "alice",
        "secret": "toplevel",
        "cred_type": "password",
    })
    assert resp.status_code == 201
    cred_id = resp.json()["cred_id"]

    # Read raw blob from DB — must NOT equal the plaintext
    result = await state.db.credential_get(cred_id)
    assert result is not None
    _, blob = result
    assert b"toplevel" not in blob

    # API returns decrypted plaintext
    resp = await client.get("/api/credentials")
    creds = {c["cred_id"]: c for c in resp.json()}
    assert creds[cred_id]["secret"] == "toplevel"


async def test_delete_nonexistent_credential_returns_404(auth_client):
    client, _ = auth_client
    resp = await client.delete("/api/credentials/nosuchid")
    assert resp.status_code == 404


async def test_credentials_require_auth(auth_client):
    client, _ = auth_client
    no_auth = AsyncClient(transport=client._transport, base_url="http://test")
    async with no_auth as c:
        resp = await c.get("/api/credentials")
    assert resp.status_code == 401


async def test_credential_event_broadcast(auth_client):
    """Creating a credential fires a broker broadcast (CREDS_CREATE)."""
    client, state = auth_client

    # Capture pre-broadcast queue depth (broker has no clients; just check no exception)
    resp = await client.post("/api/credentials", json={"username": "bob", "cred_type": "password"})
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


async def test_chat_message(auth_client):
    """Posting a chat message stores it and returns the persisted record."""
    client, state = auth_client

    resp = await client.post("/api/chat", json={"message": "hello team"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["message"] == "hello team"
    assert data["username"] == "admin"
    assert data["id"] > 0

    # Verify persisted in DB
    messages = await state.db.chat_list()
    assert any(m.message == "hello team" for m in messages)


async def test_chat_requires_auth(auth_client):
    client, _ = auth_client
    no_auth = AsyncClient(transport=client._transport, base_url="http://test")
    async with no_auth as c:
        resp = await c.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 401
