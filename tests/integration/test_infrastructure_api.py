"""Integration tests for infrastructure APIs and orchestration flows."""

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
        operators={
            "view": {"password": "viewpass", "roles": ["viewer"]},
            "admin": {"password": "adminpass", "roles": ["admin"]},
        },
        plugins={
            "listeners": ["executec2.listeners.http_listener"],
            "agents": ["executec2.agents.python_agent"],
        },
    )


class _StubExecutionAdapter:
    def __init__(self, mode: str):
        self.mode = mode

    async def execute(self, artifact_dir: Path, operation: str, timeout: int):
        filename = (
            "docker-compose.generated.yaml"
            if self.mode == "compose"
            else "main.tf.json"
        )
        result = CommandResult(
            command=["stub", self.mode, operation, filename],
            cwd=str(artifact_dir),
            returncode=0,
            stdout=f"{self.mode}:{operation}",
            stderr="",
        )
        return ExecutionResult(
            success=True,
            phase=f"{self.mode}_{operation}",
            commands=[result],
            summary=f"{self.mode} {operation} completed",
        )


@pytest.fixture
async def client(tmp_path):
    config = make_config(tmp_path)
    app = create_app(config)
    await init_app_state(app, config)
    app.state.infrastructure._compose = _StubExecutionAdapter("compose")
    app.state.infrastructure._terraform = _StubExecutionAdapter("terraform")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, app
    finally:
        await teardown_app_state(app)


async def _token(c: AsyncClient, username: str, password: str) -> str:
    resp = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _create_asset(c: AsyncClient, token: str, **payload) -> dict:
    resp = await c.post(
        "/api/infrastructure/assets",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_profile(c: AsyncClient, token: str, **payload) -> dict:
    resp = await c.post(
        "/api/traffic-profiles",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_infrastructure_asset_crud_and_stage_view(client):
    c, _app = client
    token = await _token(c, "admin", "adminpass")

    asset = await _create_asset(
        c,
        token,
        name="redir.example.com",
        asset_type="domain",
        stage=1,
        provider="cloudflare",
        config={"hostname": "redir.example.com"},
    )

    resp = await c.get(
        "/api/infrastructure/assets?stage=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()[0]["asset_id"] == asset["asset_id"]

    resp = await c.get(
        "/api/infrastructure/views/stages/1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stage"] == 1
    assert body["counts"]["domain"] == 1
    assert body["assets"][0]["name"] == "redir.example.com"


async def test_listener_profile_binding_and_inline_normalization(client):
    c, _app = client
    token = await _token(c, "admin", "adminpass")

    domain = await _create_asset(
        c,
        token,
        name="redir.example.com",
        asset_type="domain",
        stage=1,
        provider="cloudflare",
        config={"hostname": "redir.example.com"},
    )
    await _create_asset(
        c,
        token,
        name="redir-cert",
        asset_type="certificate",
        stage=1,
        provider="manual",
        parent_asset_id=domain["asset_id"],
        config={"hostname": "redir.example.com"},
    )
    redirector = await _create_asset(
        c,
        token,
        name="redirector-1",
        asset_type="redirector",
        stage=1,
        provider="nginx",
        parent_asset_id=domain["asset_id"],
        config={"listen_port": 443, "tls_termination": True},
    )
    profile = await _create_profile(
        c,
        token,
        name="edge-profile",
        listener_type="http",
        stage=1,
        host_headers=["redir.example.com"],
        callback_hostnames=["redir.example.com"],
        uris=["/api"],
        tls_mode="required",
        response_headers={"Server": "nginx"},
    )

    resp = await c.post(
        "/api/listeners",
        json={
            "listener_type": "http",
            "listener_name": "edge-listener",
            "traffic_profile_id": profile["profile_id"],
            "ingress_asset_id": redirector["asset_id"],
            "config": {
                "port_bind": 8443,
                "callback_addresses": ["redir.example.com"],
                "encrypt_key": "00" * 32,
                "beat_header": "X-Beat",
            },
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    listener = resp.json()
    assert listener["traffic_profile_id"] == profile["profile_id"]
    assert listener["ingress_asset_id"] == redirector["asset_id"]
    assert listener["config"]["uris"] == ["/api"]
    assert listener["config"]["response_headers"]["Server"] == "nginx"

    resp = await c.post(
        "/api/listeners",
        json={
            "listener_type": "http",
            "listener_name": "implicit-listener",
            "config": {
                "port_bind": 9443,
                "callback_addresses": ["redir.example.com"],
                "encrypt_key": "11" * 32,
                "beat_header": "X-Beat",
                "uris": ["/news"],
                "host_headers": ["redir.example.com"],
                "response_headers": {"Server": "edge"},
            },
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    implicit = resp.json()
    assert implicit["traffic_profile_id"]

    resp = await c.get(
        f"/api/traffic-profiles/{implicit['traffic_profile_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["profile_kind"] == "implicit"


async def test_listener_profile_compatibility_rejects_mismatched_chain(client):
    c, _app = client
    token = await _token(c, "admin", "adminpass")

    redirector = await _create_asset(
        c,
        token,
        name="redirector-1",
        asset_type="redirector",
        stage=1,
        provider="nginx",
        config={"listen_port": 443, "tls_termination": True},
    )
    profile = await _create_profile(
        c,
        token,
        name="bad-profile",
        listener_type="http",
        stage=1,
        host_headers=["wrong.example.com"],
        callback_hostnames=["wrong.example.com"],
        uris=["/api"],
        tls_mode="required",
    )

    resp = await c.post(
        "/api/listeners",
        json={
            "listener_type": "http",
            "listener_name": "edge-listener",
            "traffic_profile_id": profile["profile_id"],
            "ingress_asset_id": redirector["asset_id"],
            "config": {
                "port_bind": 8443,
                "callback_addresses": ["wrong.example.com"],
                "encrypt_key": "00" * 32,
                "beat_header": "X-Beat",
            },
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_deployment_run_plan_and_apply_for_compose_and_terraform(client):
    c, app = client
    token = await _token(c, "admin", "adminpass")

    redirector = await _create_asset(
        c,
        token,
        name="redirector-1",
        asset_type="redirector",
        stage=1,
        provider="nginx",
        deploy_target="docker_compose",
        config={"hostname": "redir.example.com", "listen_port": 443},
    )

    plan_resp = await c.post(
        "/api/infrastructure/runs",
        json={
            "asset_id": redirector["asset_id"],
            "operation": "apply",
            "target": "docker_compose",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert plan_resp.status_code == 201, plan_resp.text
    plan = plan_resp.json()
    assert plan["status"] == "planned"

    apply_resp = await c.post(
        f"/api/infrastructure/runs/{plan['run_id']}/apply",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert apply_resp.status_code == 200, apply_resp.text
    applied = apply_resp.json()
    assert applied["status"] == "applied"
    assert (Path(applied["artifact_dir"]) / "docker-compose.generated.yaml").exists()

    tf_resp = await c.post(
        "/api/infrastructure/runs",
        json={
            "asset_id": redirector["asset_id"],
            "operation": "reapply",
            "target": "terraform",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert tf_resp.status_code == 201, tf_resp.text
    tf_run = tf_resp.json()
    tf_apply = await c.post(
        f"/api/infrastructure/runs/{tf_run['run_id']}/apply",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert tf_apply.status_code == 200, tf_apply.text
    assert tf_apply.json()["status"] == "applied"
    assert (Path(tf_apply.json()["artifact_dir"]) / "main.tf.json").exists()

    drift = await c.get(
        "/api/infrastructure/views/drift-health",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert drift.status_code == 200
    assert drift.json()["counts"]["healthy"] >= 1
    assert drift.json()["counts"]["applied"] >= 2

    filtered = await c.get(
        "/api/infrastructure/runs?status=applied&operation=apply&target=docker_compose",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert filtered.status_code == 200
    assert filtered.json()[0]["operation"] == "apply"

    from executec2.server.routes.sync import _get_db_snapshot

    snapshot = await _get_db_snapshot(
        app.state.db,
        ["infrastructure", "traffic_profiles", "deployment_runs"],
    )
    assert len(snapshot["infrastructure"]) >= 1
    assert len(snapshot["deployment_runs"]) >= 2


async def test_plan_rotate_creates_replacement_and_flips_topology(client):
    c, _app = client
    token = await _token(c, "admin", "adminpass")

    redirector = await _create_asset(
        c,
        token,
        name="redirector-1",
        asset_type="redirector",
        stage=1,
        provider="nginx",
        config={"hostname": "redir.example.com", "listen_port": 443},
    )
    child = await _create_asset(
        c,
        token,
        name="redir-cert",
        asset_type="certificate",
        stage=1,
        provider="manual",
        parent_asset_id=redirector["asset_id"],
        config={"hostname": "redir.example.com"},
    )

    run_resp = await c.post(
        "/api/infrastructure/runs",
        json={
            "asset_id": redirector["asset_id"],
            "operation": "rotate",
            "target": "docker_compose",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert run_resp.status_code == 201, run_resp.text
    run = run_resp.json()
    assert run["replacement_asset_id"]

    apply_resp = await c.post(
        f"/api/infrastructure/runs/{run['run_id']}/apply",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert apply_resp.status_code == 200, apply_resp.text
    applied = apply_resp.json()
    assert applied["status"] == "applied"
    assert applied["rollback_data"]["child_asset_ids"] == [child["asset_id"]]

    child_resp = await c.get(
        f"/api/infrastructure/assets/{child['asset_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert child_resp.status_code == 200
    assert child_resp.json()["parent_asset_id"] == run["replacement_asset_id"]


async def test_rotation_failure_preserves_topology_and_marks_run_failed(client):
    c, _app = client
    token = await _token(c, "admin", "adminpass")

    redirector = await _create_asset(
        c,
        token,
        name="redirector-fail",
        asset_type="redirector",
        stage=1,
        provider="nginx",
        config={"hostname": "fail.example.com", "listen_port": 443, "force_health_fail": True},
    )
    child = await _create_asset(
        c,
        token,
        name="fail-cert",
        asset_type="certificate",
        stage=1,
        provider="manual",
        parent_asset_id=redirector["asset_id"],
        config={"hostname": "fail.example.com"},
    )

    run_resp = await c.post(
        "/api/infrastructure/runs",
        json={
            "asset_id": redirector["asset_id"],
            "operation": "rotate",
            "target": "docker_compose",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    run = run_resp.json()

    apply_resp = await c.post(
        f"/api/infrastructure/runs/{run['run_id']}/apply",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert apply_resp.status_code == 200
    failed = apply_resp.json()
    assert failed["status"] == "failed"
    assert failed["failure_phase"] == "health_check"

    child_resp = await c.get(
        f"/api/infrastructure/assets/{child['asset_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert child_resp.json()["parent_asset_id"] == redirector["asset_id"]


async def test_teardown_records_audit_state(client):
    c, _app = client
    token = await _token(c, "admin", "adminpass")
    redirector = await _create_asset(
        c,
        token,
        name="redirector-down",
        asset_type="redirector",
        stage=1,
        provider="nginx",
        config={"hostname": "redir.example.com", "listen_port": 443},
    )

    run_resp = await c.post(
        "/api/infrastructure/runs",
        json={
            "asset_id": redirector["asset_id"],
            "operation": "teardown",
            "target": "docker_compose",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    run = run_resp.json()

    apply_resp = await c.post(
        f"/api/infrastructure/runs/{run['run_id']}/apply",
        headers={"Authorization": f"Bearer {token}"},
    )
    torn = apply_resp.json()
    assert torn["status"] == "torn_down"
    assert torn["backend_commands"]


async def test_plan_creation_rejects_incompatible_asset_chain(client):
    c, _app = client
    token = await _token(c, "admin", "adminpass")
    profile = await _create_profile(
        c,
        token,
        name="strict-profile",
        listener_type="http",
        stage=1,
        host_headers=["redir.example.com"],
        callback_hostnames=["redir.example.com"],
        response_headers={"Server": "edge"},
        tls_mode="required",
    )
    redirector = await _create_asset(
        c,
        token,
        name="bad-redirector",
        asset_type="redirector",
        stage=1,
        provider="nginx",
        traffic_profile_id=profile["profile_id"],
        config={"blocked_response_headers": ["server"], "origin_ports": [443]},
    )

    resp = await c.post(
        "/api/infrastructure/runs",
        json={
            "asset_id": redirector["asset_id"],
            "operation": "apply",
            "target": "docker_compose",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_infrastructure_rbac_viewer_read_only(client):
    c, _app = client
    admin_token = await _token(c, "admin", "adminpass")
    viewer_token = await _token(c, "view", "viewpass")
    await _create_asset(
        c,
        admin_token,
        name="redir.example.com",
        asset_type="domain",
        stage=1,
        provider="cloudflare",
        config={"hostname": "redir.example.com"},
    )

    resp = await c.get(
        "/api/infrastructure/assets",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200

    resp = await c.post(
        "/api/infrastructure/assets",
        json={
            "name": "denied.example.com",
            "asset_type": "domain",
            "stage": 1,
            "provider": "cloudflare",
            "config": {"hostname": "denied.example.com"},
        },
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 403
