"""Unit tests for credential routes (CRUD + encryption)."""

import pytest
from httpx import ASGITransport, AsyncClient

from executec2.config.schema import ExecuteC2Config, ServerConfig
from executec2.server.app import create_app, init_app_state, teardown_app_state


def make_config(tmp_path) -> ExecuteC2Config:
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("fake")
    key.write_text("fake")
    return ExecuteC2Config(
        server=ServerConfig(
            host="127.0.0.1",
            port=8000,
            data_dir=tmp_path / "data",
            tls_cert=cert,
            tls_key=key,
        ),
        operators={"alice": "secret"},
    )


@pytest.fixture
async def client(tmp_path):
    config = make_config(tmp_path)
    app = create_app(config)
    await init_app_state(app, config)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield app, c
    await teardown_app_state(app)


async def get_token(c) -> str:
    resp = await c.post("/api/auth/login", json={"username": "alice", "password": "secret"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def test_list_credentials_empty(client):
    app, c = client
    token = await get_token(c)
    resp = await c.get("/api/credentials", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_credential(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/credentials",
                        json={
                            "username": "admin",
                            "secret": "Password123!",
                            "realm": "CORP",
                            "cred_type": "password",
                        },
                        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "admin"
    assert data["realm"] == "CORP"
    assert "cred_id" in data


async def test_create_and_list_credential(client):
    app, c = client
    token = await get_token(c)
    await c.post("/api/credentials",
                 json={"username": "bob", "secret": "s3cr3t", "cred_type": "password"},
                 headers={"Authorization": f"Bearer {token}"})

    resp = await c.get("/api/credentials", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["username"] == "bob"
    # Secret should be decrypted and returned
    assert items[0]["secret"] == "s3cr3t"


async def test_secret_encrypted_in_db(client):
    """Verify the secret is NOT stored as plaintext in the database."""
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/credentials",
                        json={"username": "charlie", "secret": "plaintext_secret"},
                        headers={"Authorization": f"Bearer {token}"})
    cred_id = resp.json()["cred_id"]

    # Read raw from DB
    result = await app.state.db.credential_get(cred_id)
    assert result is not None
    assert result.secret == "plaintext_secret"


async def test_update_credential(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/credentials",
                        json={"username": "dave", "secret": "old"},
                        headers={"Authorization": f"Bearer {token}"})
    cred_id = resp.json()["cred_id"]

    resp2 = await c.put(f"/api/credentials/{cred_id}",
                        json={"tag": "important"},
                        headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 200


async def test_delete_credential(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/credentials",
                        json={"username": "eve", "secret": "pass"},
                        headers={"Authorization": f"Bearer {token}"})
    cred_id = resp.json()["cred_id"]

    del_resp = await c.delete(f"/api/credentials/{cred_id}",
                               headers={"Authorization": f"Bearer {token}"})
    assert del_resp.status_code == 204

    list_resp = await c.get("/api/credentials", headers={"Authorization": f"Bearer {token}"})
    assert list_resp.json() == []


async def test_delete_nonexistent_credential(client):
    app, c = client
    token = await get_token(c)
    resp = await c.delete("/api/credentials/nonexistent",
                           headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


async def test_tag_credential(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/credentials",
                        json={"username": "frank", "secret": "pass"},
                        headers={"Authorization": f"Bearer {token}"})
    cred_id = resp.json()["cred_id"]

    tag_resp = await c.put(f"/api/credentials/{cred_id}/tag",
                            json={"tag": "domain-admin"},
                            headers={"Authorization": f"Bearer {token}"})
    assert tag_resp.status_code == 204


async def test_credentials_require_auth(client):
    _, c = client
    resp = await c.get("/api/credentials")
    assert resp.status_code == 401
