"""Unit tests for infrastructure helpers and adapters."""

from pathlib import Path

from executec2.server.models import (
    DeployTarget,
    InfraStage,
    InfrastructureAssetData,
    InfrastructureAssetType,
    TrafficProfileData,
    TrafficProfileKind,
    TrafficProfileTLSMode,
)


def test_normalize_inline_profile_config_extracts_profile_fields():
    from executec2.infrastructure.profiles import normalize_listener_profile_payload

    runtime_config = {
        "port_bind": 8443,
        "callback_addresses": ["edge.example.com"],
        "encrypt_key": "00" * 32,
        "beat_header": "X-Beat",
        "uris": ["/news", "/health"],
        "http_method": "GET",
        "host_headers": ["edge.example.com"],
        "response_headers": {"Server": "nginx"},
        "trust_x_forwarded_for": True,
    }

    profile, cleaned = normalize_listener_profile_payload(
        listener_name="listener-one",
        listener_type="http",
        config=runtime_config,
    )

    assert profile is not None
    assert profile.profile_kind is TrafficProfileKind.IMPLICIT
    assert profile.host_headers == ["edge.example.com"]
    assert profile.uris == ["/news", "/health"]
    assert cleaned["port_bind"] == 8443
    assert cleaned["callback_addresses"] == ["edge.example.com"]
    assert "host_headers" not in cleaned
    assert "response_headers" not in cleaned


def test_profile_compatibility_accepts_matching_chain():
    from executec2.infrastructure.compat import validate_profile_compatibility

    profile = TrafficProfileData(
        profile_id="profile-1",
        name="https edge",
        listener_type="http",
        host_headers=["redir.example.com"],
        callback_hostnames=["redir.example.com"],
        uris=["/api"],
        tls_mode=TrafficProfileTLSMode.REQUIRED,
        stage=InfraStage.STAGE_1,
    )
    chain = [
        InfrastructureAssetData(
            asset_id="domain-1",
            name="redir.example.com",
            asset_type=InfrastructureAssetType.DOMAIN,
            stage=InfraStage.STAGE_1,
            provider="manual",
            config={"hostname": "redir.example.com"},
        ),
        InfrastructureAssetData(
            asset_id="cert-1",
            name="redir-cert",
            asset_type=InfrastructureAssetType.CERTIFICATE,
            stage=InfraStage.STAGE_1,
            provider="manual",
            config={"hostname": "redir.example.com"},
        ),
        InfrastructureAssetData(
            asset_id="redir-1",
            name="redirector-1",
            asset_type=InfrastructureAssetType.REDIRECTOR,
            stage=InfraStage.STAGE_1,
            provider="nginx",
            config={"listen_port": 443, "tls_termination": True},
        ),
    ]

    validate_profile_compatibility(profile, chain, port_bind=443)


def test_profile_compatibility_rejects_host_mismatch():
    from executec2.infrastructure.compat import (
        IncompatibleProfileError,
        validate_profile_compatibility,
    )

    profile = TrafficProfileData(
        profile_id="profile-1",
        name="https edge",
        listener_type="http",
        host_headers=["wrong.example.com"],
        callback_hostnames=["wrong.example.com"],
        uris=["/api"],
        tls_mode=TrafficProfileTLSMode.REQUIRED,
        stage=InfraStage.STAGE_1,
    )
    chain = [
        InfrastructureAssetData(
            asset_id="domain-1",
            name="redir.example.com",
            asset_type=InfrastructureAssetType.DOMAIN,
            stage=InfraStage.STAGE_1,
            provider="manual",
            config={"hostname": "redir.example.com"},
        )
    ]

    try:
        validate_profile_compatibility(profile, chain, port_bind=443)
    except IncompatibleProfileError as exc:
        assert "wrong.example.com" in str(exc)
    else:
        raise AssertionError("Expected compatibility validation to fail")


def test_profile_compatibility_rejects_blocked_response_headers():
    from executec2.infrastructure.compat import (
        IncompatibleProfileError,
        validate_profile_compatibility,
    )

    profile = TrafficProfileData(
        profile_id="profile-2",
        name="header-profile",
        listener_type="http",
        response_headers={"Server": "edge"},
        stage=InfraStage.STAGE_1,
    )
    chain = [
        InfrastructureAssetData(
            asset_id="redir-1",
            name="redirector-1",
            asset_type=InfrastructureAssetType.REDIRECTOR,
            stage=InfraStage.STAGE_1,
            provider="nginx",
            config={"blocked_response_headers": ["server"]},
        )
    ]

    try:
        validate_profile_compatibility(profile, chain, port_bind=443)
    except IncompatibleProfileError as exc:
        assert "response headers" in str(exc)
    else:
        raise AssertionError("Expected compatibility validation to fail")


async def test_fake_adapters_return_deterministic_responses(tmp_path: Path):
    from executec2.infrastructure.adapters import FakeCloudflareAdapter, FakeNginxRedirectorAdapter
    from executec2.infrastructure.service import RenderedArtifacts

    asset = InfrastructureAssetData(
        asset_id="redir-1",
        name="redirector-1",
        asset_type=InfrastructureAssetType.REDIRECTOR,
        stage=InfraStage.STAGE_1,
        provider="nginx",
        config={"hostname": "redir.example.com"},
        deploy_target=DeployTarget.DOCKER_COMPOSE,
    )
    artifacts = RenderedArtifacts(
        artifact_dir=tmp_path,
        manifest={"asset_id": asset.asset_id},
        files={"docker-compose.generated.yaml": "services: {}"},
        checksums={"docker-compose.generated.yaml": "abc123"},
    )

    cf = FakeCloudflareAdapter()
    nginx = FakeNginxRedirectorAdapter()

    cf_result = await cf.apply(asset, artifacts)
    nginx_result = await nginx.apply(asset, artifacts)
    health = await nginx.health_check(asset)

    assert cf_result["provider"] == "cloudflare"
    assert nginx_result["provider"] == "nginx"
    assert health["status"] == "healthy"


async def test_execution_adapters_capture_command_sequences(tmp_path: Path):
    from executec2.infrastructure.adapters import (
        CommandResult,
        DockerComposeExecutionAdapter,
        TerraformExecutionAdapter,
    )

    class StubRunner:
        def __init__(self):
            self.commands = []

        async def run(self, command, *, cwd, timeout):
            self.commands.append((command, cwd, timeout))
            return CommandResult(
                command=command,
                cwd=str(cwd),
                returncode=0,
                stdout="ok",
                stderr="",
            )

    runner = StubRunner()
    compose = DockerComposeExecutionAdapter(runner=runner, binary="docker")
    terraform = TerraformExecutionAdapter(runner=runner, binary="terraform")
    (tmp_path / "docker-compose.generated.yaml").write_text("services: {}")
    (tmp_path / "main.tf.json").write_text("{}")

    compose_result = await compose.execute(tmp_path, "apply", 30)
    terraform_result = await terraform.execute(tmp_path, "teardown", 30)

    assert compose_result.success is True
    assert terraform_result.success is True
    assert runner.commands[0][0][:3] == ["docker", "compose", "-f"]
    assert runner.commands[-1][0][1] == "destroy"
