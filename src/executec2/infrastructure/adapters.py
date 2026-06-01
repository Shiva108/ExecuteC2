"""Provider and execution adapters for infrastructure orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from executec2.server.models import InfrastructureAssetData


@dataclass(slots=True)
class CommandResult:
    command: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExecutionResult:
    success: bool
    phase: str
    commands: list[CommandResult]
    summary: str

    def commands_as_dicts(self) -> list[dict[str, Any]]:
        return [command.as_dict() for command in self.commands]


class CommandRunner(Protocol):
    async def run(self, command: list[str], *, cwd: Path, timeout: int) -> CommandResult: ...


class SubprocessCommandRunner:
    async def run(self, command: list[str], *, cwd: Path, timeout: int) -> CommandResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return CommandResult(
                command=command,
                cwd=str(cwd),
                returncode=127,
                stdout="",
                stderr=str(exc),
            )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            return CommandResult(
                command=command,
                cwd=str(cwd),
                returncode=process.returncode if process.returncode is not None else 124,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                timed_out=True,
            )

        return CommandResult(
            command=command,
            cwd=str(cwd),
            returncode=process.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )


async def _run_command_sequence(
    runner: CommandRunner,
    artifact_dir: Path,
    timeout: int,
    commands: list[tuple[str, list[str]]],
) -> ExecutionResult:
    results: list[CommandResult] = []
    for phase, command in commands:
        result = await runner.run(command, cwd=artifact_dir, timeout=timeout)
        results.append(result)
        if result.timed_out:
            return ExecutionResult(
                success=False,
                phase=phase,
                commands=results,
                summary=f"{phase} timed out",
            )
        if result.returncode != 0:
            return ExecutionResult(
                success=False,
                phase=phase,
                commands=results,
                summary=f"{phase} failed with exit code {result.returncode}",
            )
    return ExecutionResult(
        success=True,
        phase=commands[-1][0],
        commands=results,
        summary=f"{commands[-1][0]} completed",
    )


class TerraformExecutionAdapter:
    def __init__(self, runner: CommandRunner | None = None, binary: str = "terraform"):
        self._runner = runner or SubprocessCommandRunner()
        self._binary = binary

    async def execute(self, artifact_dir: Path, operation: str, timeout: int) -> ExecutionResult:
        commands = [
            ("terraform_init", [self._binary, "init", "-input=false"]),
            ("terraform_plan", [self._binary, "plan", "-input=false", "-out=tfplan"]),
        ]
        if operation == "teardown":
            commands.append(
                ("terraform_destroy", [self._binary, "destroy", "-input=false", "-auto-approve"])
            )
        else:
            commands.append(
                ("terraform_apply", [self._binary, "apply", "-input=false", "-auto-approve"])
            )
        return await _run_command_sequence(self._runner, artifact_dir, timeout, commands)


class DockerComposeExecutionAdapter:
    def __init__(self, runner: CommandRunner | None = None, binary: str = "docker"):
        self._runner = runner or SubprocessCommandRunner()
        self._binary = binary

    async def execute(self, artifact_dir: Path, operation: str, timeout: int) -> ExecutionResult:
        compose_file = artifact_dir / "docker-compose.generated.yaml"
        commands = [
            (
                "compose_config",
                [self._binary, "compose", "-f", str(compose_file), "config"],
            )
        ]
        if operation == "teardown":
            commands.append(
                ("compose_down", [self._binary, "compose", "-f", str(compose_file), "down"])
            )
        else:
            commands.append(
                (
                    "compose_up",
                    [self._binary, "compose", "-f", str(compose_file), "up", "-d"],
                )
            )
        return await _run_command_sequence(self._runner, artifact_dir, timeout, commands)


class CloudflareAdapter:
    provider_name = "cloudflare"

    async def apply(self, asset: InfrastructureAssetData, artifacts) -> dict[str, Any]:
        records = artifacts.manifest.get("dns_records", [])
        return {
            "provider": self.provider_name,
            "records": records,
            "artifact_dir": str(artifacts.artifact_dir),
        }

    async def health_check(self, asset: InfrastructureAssetData) -> dict[str, Any]:
        hostname = str(asset.config.get("hostname", asset.name))
        return {
            "provider": self.provider_name,
            "status": "failing" if asset.config.get("force_health_fail") else "healthy",
            "endpoint_probes": [{"hostname": hostname, "kind": "dns"}],
        }


class NginxRedirectorAdapter:
    provider_name = "nginx"

    async def apply(self, asset: InfrastructureAssetData, artifacts) -> dict[str, Any]:
        config_path = Path(artifacts.artifact_dir) / "nginx.redirector.conf"
        return {
            "provider": self.provider_name,
            "config_path": str(config_path),
            "hostname": asset.config.get("hostname", asset.name),
        }

    async def health_check(self, asset: InfrastructureAssetData) -> dict[str, Any]:
        hostname = str(asset.config.get("hostname", asset.name))
        port = int(asset.config.get("listen_port", 443))
        return {
            "provider": self.provider_name,
            "status": "failing" if asset.config.get("force_health_fail") else "healthy",
            "endpoint_probes": [{"hostname": hostname, "port": port, "kind": "https"}],
        }


class FakeCloudflareAdapter(CloudflareAdapter):
    async def apply(self, asset: InfrastructureAssetData, artifacts) -> dict[str, Any]:
        result = await super().apply(asset, artifacts)
        result["mode"] = "fake"
        return result


class FakeNginxRedirectorAdapter(NginxRedirectorAdapter):
    async def apply(self, asset: InfrastructureAssetData, artifacts) -> dict[str, Any]:
        result = await super().apply(asset, artifacts)
        result["mode"] = "fake"
        return result
