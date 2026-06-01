"""Integration tests for infrastructure UI routes."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from executec2.config.schema import ExecuteC2Config, ServerConfig
from executec2.infrastructure.adapters import CommandResult, ExecutionResult
from executec2.server.app import create_app, init_app_state, teardown_app_state


def make_config(tmp_path: Path) -> ExecuteC2Config:
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
        ),
        operators={"admin": {"password": "adminpass", "roles": ["admin"]}},
    )


class _StubExecutionAdapter:
    async def execute(self, artifact_dir: Path, operation: str, timeout: int):
        result = CommandResult(
            command=["stub", operation],
            cwd=str(artifact_dir),
            returncode=0,
            stdout="ok",
            stderr="",
        )
        return ExecutionResult(
            success=True,
            phase=operation,
            commands=[result],
            summary="ok",
        )


@pytest.fixture
async def client(tmp_path):
    config = make_config(tmp_path)
    app = create_app(config)
    await init_app_state(app, config)
    app.state.infrastructure._compose = _StubExecutionAdapter()
    app.state.infrastructure._terraform = _StubExecutionAdapter()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        await teardown_app_state(app)


async def _ui_login(c: AsyncClient) -> str:
    resp = await c.post(
        "/ui/login",
        data={"username": "admin", "password": "adminpass"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    csrf_token = c.cookies.get("ec2_csrf_token")
    assert csrf_token
    return csrf_token


async def test_ui_login_sets_auth_and_csrf_cookies(client):
    resp = await client.get("/ui/login")
    assert resp.status_code == 200
    assert "ExecuteC2 Login" in resp.text

    csrf_token = await _ui_login(client)
    assert client.cookies.get("ec2_access_token")
    assert csrf_token


async def test_stage_page_requires_auth_and_renders_assets(client):
    token_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "adminpass"},
    )
    token = token_resp.json()["access_token"]
    asset_resp = await client.post(
        "/api/infrastructure/assets",
        json={
            "name": "redir.example.com",
            "asset_type": "domain",
            "stage": 1,
            "provider": "cloudflare",
            "config": {"hostname": "redir.example.com"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert asset_resp.status_code == 201, asset_resp.text

    resp = await client.get("/ui/infrastructure/stages/1", follow_redirects=False)
    assert resp.status_code == 303

    await _ui_login(client)
    resp = await client.get("/ui/infrastructure/stages/1")
    assert resp.status_code == 200
    assert "redir.example.com" in resp.text
    assert "Stage 1" in resp.text


async def test_ui_mutation_requires_csrf(client):
    csrf_token = await _ui_login(client)

    resp = await client.post(
        "/ui/infrastructure/assets",
        data={
            "name": "redir.example.com",
            "asset_type": "domain",
            "stage": "1",
            "provider": "cloudflare",
            "hostname": "redir.example.com",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 403

    resp = await client.post(
        "/ui/infrastructure/assets",
        data={
            "csrf_token": csrf_token,
            "name": "redir.example.com",
            "asset_type": "domain",
            "stage": "1",
            "provider": "cloudflare",
            "hostname": "redir.example.com",
        },
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/ui/infrastructure/stages/1")


async def test_ui_run_pages_render_and_execute_plan_first_flow(client):
    token_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "adminpass"},
    )
    token = token_resp.json()["access_token"]
    asset_resp = await client.post(
        "/api/infrastructure/assets",
        json={
            "name": "redirector-ui",
            "asset_type": "redirector",
            "stage": 1,
            "provider": "nginx",
            "config": {"hostname": "redir.example.com", "listen_port": 443},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    asset = asset_resp.json()

    csrf_token = await _ui_login(client)
    plan_resp = await client.post(
        "/ui/infrastructure/runs",
        data={
            "csrf_token": csrf_token,
            "asset_id": asset["asset_id"],
            "operation": "apply",
            "target": "docker_compose",
        },
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False,
    )
    assert plan_resp.status_code == 303
    run_url = plan_resp.headers["location"]

    detail = await client.get(run_url)
    assert detail.status_code == 200
    assert "Command Transcript" in detail.text

    apply_resp = await client.post(
        f"{run_url}/apply",
        data={"csrf_token": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False,
    )
    assert apply_resp.status_code == 303

    runs_page = await client.get("/ui/infrastructure/runs")
    assert runs_page.status_code == 200
    assert "Deployment Runs" in runs_page.text

    drift_page = await client.get("/ui/infrastructure/drift")
    assert drift_page.status_code == 200
    assert "Drift And Health Summary" in drift_page.text
