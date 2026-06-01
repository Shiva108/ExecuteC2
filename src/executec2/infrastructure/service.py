"""Infrastructure inventory and orchestration services."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from executec2.infrastructure.adapters import (
    CloudflareAdapter,
    DockerComposeExecutionAdapter,
    NginxRedirectorAdapter,
    TerraformExecutionAdapter,
)
from executec2.infrastructure.compat import validate_profile_compatibility
from executec2.server.models import (
    DeploymentRunData,
    DeploymentRunStatus,
    DeployTarget,
    InfraHealthSnapshotData,
    InfraHealthStatus,
    InfraStage,
    InfrastructureAssetData,
    InfrastructureAssetType,
)

_RUN_OPERATIONS = {"apply", "reapply", "rotate", "teardown"}


@dataclass(slots=True)
class RenderedArtifacts:
    artifact_dir: Path
    manifest: dict
    files: dict[str, str]
    checksums: dict[str, str]


class InfrastructureService:
    def __init__(self, db, data_dir: Path):
        self._db = db
        self._root = Path(data_dir) / "infrastructure" / "runs"
        self._root.mkdir(parents=True, exist_ok=True)
        self._cloudflare = CloudflareAdapter()
        self._nginx = NginxRedirectorAdapter()
        self._terraform = TerraformExecutionAdapter()
        self._compose = DockerComposeExecutionAdapter()

    async def get_asset_chain(self, asset_id: str) -> list[InfrastructureAssetData]:
        asset = await self._db.infrastructure_asset_get(asset_id)
        if asset is None:
            return []
        chain = [asset]
        current = asset
        while current.parent_asset_id:
            parent = await self._db.infrastructure_asset_get(current.parent_asset_id)
            if parent is None:
                break
            chain.append(parent)
            current = parent
        return chain

    async def create_plan(
        self,
        *,
        asset_id: str,
        operation: str,
        target: DeployTarget,
        created_by: str,
    ) -> DeploymentRunData:
        if operation not in _RUN_OPERATIONS:
            raise ValueError("Unsupported operation")

        asset = await self._db.infrastructure_asset_get(asset_id)
        if asset is None:
            raise ValueError("Asset not found")

        await self._validate_plan_compatibility(asset)

        run_id = uuid4().hex
        replacement_asset_id = ""
        render_asset = asset
        rollback_data: dict = {}
        if operation == "rotate":
            replacement = await self._create_replacement_asset(asset, run_id)
            replacement_asset_id = replacement.asset_id
            render_asset = replacement
            rollback_data = {
                "original_asset_id": asset.asset_id,
                "replacement_asset_id": replacement.asset_id,
                "original_parent_asset_id": asset.parent_asset_id,
            }

        artifacts = await self._render_artifacts(render_asset, run_id, target, operation)
        now = datetime.now(UTC)
        manifest = dict(artifacts.manifest)
        manifest["checksums"] = artifacts.checksums
        run = DeploymentRunData(
            run_id=run_id,
            asset_id=asset_id,
            operation=operation,
            target=target,
            status=DeploymentRunStatus.PLANNED,
            created_by=created_by,
            artifact_dir=str(artifacts.artifact_dir),
            plan_data=manifest,
            provider_responses={},
            replacement_asset_id=replacement_asset_id,
            rollback_data=rollback_data,
            timeout_seconds=int(asset.config.get("deployment_timeout", 90)),
            create_time=now,
            update_time=now,
        )
        await self._db.deployment_run_insert(run)
        return run

    async def apply_run(self, run_id: str) -> DeploymentRunData:
        run = await self._db.deployment_run_get(run_id)
        if run is None:
            raise ValueError("Run not found")
        asset = await self._db.infrastructure_asset_get(run.asset_id)
        if asset is None:
            raise ValueError("Asset not found")

        render_asset = asset
        if run.replacement_asset_id:
            replacement = await self._db.infrastructure_asset_get(run.replacement_asset_id)
            if replacement is None:
                raise ValueError("Replacement asset not found")
            render_asset = replacement

        status = DeploymentRunStatus.APPLYING
        if run.operation == "rotate":
            status = DeploymentRunStatus.ROTATING
        elif run.operation == "teardown":
            status = DeploymentRunStatus.TEARING_DOWN

        started_at = datetime.now(UTC)
        await self._db.deployment_run_update(
            run_id,
            status=status,
            started_at=started_at,
            update_time=started_at,
            failure_reason="",
            failure_phase="",
            execution_log=[],
            backend_commands=[],
            health_checks=[],
        )

        artifacts = await self._render_artifacts(
            render_asset,
            run.run_id,
            run.target,
            run.operation,
        )
        execution = await self._execute_target(
            target=run.target,
            artifact_dir=artifacts.artifact_dir,
            operation=run.operation,
            timeout=run.timeout_seconds,
        )
        backend_commands = execution.commands_as_dicts()
        execution_log = [
            {
                "phase": execution.phase,
                "summary": execution.summary,
                "success": execution.success,
            }
        ]
        if not execution.success:
            await self._mark_run_failed(
                run=run,
                asset=render_asset,
                failure_reason=execution.summary,
                failure_phase=execution.phase,
                backend_commands=backend_commands,
                execution_log=execution_log,
                health_checks=[],
                provider_responses={},
            )
            updated = await self._db.deployment_run_get(run_id)
            assert updated is not None
            return updated

        provider_responses = await self._collect_provider_responses(render_asset, artifacts)
        health_checks = await self._collect_health_checks(render_asset)
        health_summary = {
            "target": run.target.value,
            "operation": run.operation,
            "commands": backend_commands,
            "providers": provider_responses,
            "health_checks": health_checks,
            "drift": {"detected": False},
        }

        if any(check.get("status") != "healthy" for check in health_checks):
            await self._mark_run_failed(
                run=run,
                asset=render_asset,
                failure_reason="Health checks failed",
                failure_phase="health_check",
                backend_commands=backend_commands,
                execution_log=execution_log,
                health_checks=health_checks,
                provider_responses=provider_responses,
            )
            snapshot = InfraHealthSnapshotData(
                snapshot_id=uuid4().hex,
                asset_id=render_asset.asset_id,
                status=InfraHealthStatus.FAILING,
                summary="Health checks failed",
                details=health_summary,
                observed_at=datetime.now(UTC),
            )
            await self._db.infra_health_snapshot_insert(snapshot)
            updated = await self._db.deployment_run_get(run_id)
            assert updated is not None
            return updated

        now = datetime.now(UTC)
        final_status = DeploymentRunStatus.APPLIED
        if run.operation == "teardown":
            final_status = DeploymentRunStatus.TORN_DOWN
        elif run.operation == "rotate":
            await self._flip_rotation(asset, render_asset, run)

        checksum = artifacts.checksums.get("manifest.json", "")
        await self._db.infrastructure_asset_update(
            render_asset.asset_id,
            health=InfraHealthStatus.HEALTHY
            if run.operation != "teardown"
            else InfraHealthStatus.UNKNOWN,
            rendered_checksum=checksum,
            last_deployment_run_id=run.run_id,
            last_health_observed_at=now,
            dns_state="destroyed" if run.operation == "teardown" else "applied",
            update_time=now,
        )
        if run.operation == "rotate":
            await self._db.infrastructure_asset_update(
                asset.asset_id,
                health=InfraHealthStatus.UNKNOWN,
                dns_state="rotated",
                update_time=now,
            )

        snapshot = InfraHealthSnapshotData(
            snapshot_id=uuid4().hex,
            asset_id=render_asset.asset_id,
            status=InfraHealthStatus.HEALTHY
            if run.operation != "teardown"
            else InfraHealthStatus.UNKNOWN,
            summary="Deployment applied" if run.operation != "teardown" else "Deployment torn down",
            details=health_summary,
            observed_at=now,
        )
        await self._db.infra_health_snapshot_insert(snapshot)
        await self._db.deployment_run_update(
            run.run_id,
            status=final_status,
            artifact_dir=str(artifacts.artifact_dir),
            plan_data=dict(artifacts.manifest, checksums=artifacts.checksums),
            provider_responses=provider_responses,
            backend_commands=backend_commands,
            execution_log=execution_log,
            health_checks=health_checks,
            finished_at=now,
            update_time=now,
        )
        updated = await self._db.deployment_run_get(run.run_id)
        assert updated is not None
        return updated

    async def build_stage_view(self, stage: InfraStage) -> dict:
        assets = await self._db.infrastructure_asset_list(stage=stage)
        counts: dict[str, int] = {}
        for asset in assets:
            counts[asset.asset_type.value] = counts.get(asset.asset_type.value, 0) + 1
        return {
            "stage": int(stage),
            "assets": [asset.model_dump(mode="json") for asset in assets],
            "counts": counts,
        }

    async def build_drift_health_summary(self) -> dict:
        assets = await self._db.infrastructure_asset_list()
        runs = await self._db.deployment_run_list()
        counts = {
            "healthy": sum(1 for asset in assets if asset.health == InfraHealthStatus.HEALTHY),
            "drifted": sum(1 for run in runs if run.status == DeploymentRunStatus.DRIFTED),
            "applied": sum(1 for run in runs if run.status == DeploymentRunStatus.APPLIED),
            "torn_down": sum(1 for run in runs if run.status == DeploymentRunStatus.TORN_DOWN),
            "failed": sum(1 for run in runs if run.status == DeploymentRunStatus.FAILED),
        }
        return {
            "counts": counts,
            "assets": [asset.model_dump(mode="json") for asset in assets],
            "runs": [run.model_dump(mode="json") for run in runs],
        }

    async def build_ingress_chain_view(self, asset_id: str) -> dict:
        chain = await self.get_asset_chain(asset_id)
        return {"asset_id": asset_id, "chain": [asset.model_dump(mode="json") for asset in chain]}

    async def _execute_target(
        self,
        *,
        target: DeployTarget,
        artifact_dir: Path,
        operation: str,
        timeout: int,
    ):
        if target is DeployTarget.DOCKER_COMPOSE:
            return await self._compose.execute(artifact_dir, operation, timeout)
        return await self._terraform.execute(artifact_dir, operation, timeout)

    async def _collect_provider_responses(
        self,
        asset: InfrastructureAssetData,
        artifacts: RenderedArtifacts,
    ) -> dict[str, dict]:
        responses: dict[str, dict] = {}
        if asset.asset_type in {InfrastructureAssetType.DOMAIN, InfrastructureAssetType.CDN_EDGE}:
            responses["cloudflare"] = await self._cloudflare.apply(asset, artifacts)
        else:
            responses["nginx"] = await self._nginx.apply(asset, artifacts)
            responses["cloudflare"] = await self._cloudflare.apply(asset, artifacts)
        return responses

    async def _collect_health_checks(self, asset: InfrastructureAssetData) -> list[dict]:
        checks = []
        if asset.asset_type in {InfrastructureAssetType.DOMAIN, InfrastructureAssetType.CDN_EDGE}:
            checks.append(await self._cloudflare.health_check(asset))
        else:
            checks.append(await self._nginx.health_check(asset))
            checks.append(await self._cloudflare.health_check(asset))
        return checks

    async def _mark_run_failed(
        self,
        *,
        run: DeploymentRunData,
        asset: InfrastructureAssetData,
        failure_reason: str,
        failure_phase: str,
        backend_commands: list[dict],
        execution_log: list[dict],
        health_checks: list[dict],
        provider_responses: dict[str, dict],
    ) -> None:
        now = datetime.now(UTC)
        await self._db.infrastructure_asset_update(
            asset.asset_id,
            health=InfraHealthStatus.FAILING,
            last_health_observed_at=now,
            update_time=now,
        )
        await self._db.deployment_run_update(
            run.run_id,
            status=DeploymentRunStatus.FAILED,
            failure_reason=failure_reason,
            failure_phase=failure_phase,
            provider_responses=provider_responses,
            backend_commands=backend_commands,
            execution_log=execution_log,
            health_checks=health_checks,
            finished_at=now,
            update_time=now,
        )

    async def _validate_plan_compatibility(self, asset: InfrastructureAssetData) -> None:
        profile = None
        chain_asset_id = asset.asset_id
        port_bind = int(asset.config.get("origin_port", asset.config.get("listen_port", 0)))

        if asset.traffic_profile_id:
            profile = await self._db.traffic_profile_get(asset.traffic_profile_id)
        elif asset.linked_listener_name:
            listener = await self._db.listener_get(asset.linked_listener_name)
            if listener and listener.traffic_profile_id:
                profile = await self._db.traffic_profile_get(listener.traffic_profile_id)
                chain_asset_id = listener.ingress_asset_id or asset.asset_id
                port_bind = int(listener.config.get("port_bind", port_bind))
        elif asset.asset_type is InfrastructureAssetType.LISTENER:
            listener = await self._db.listener_get(asset.name)
            if listener and listener.traffic_profile_id:
                profile = await self._db.traffic_profile_get(listener.traffic_profile_id)
                chain_asset_id = listener.ingress_asset_id or asset.asset_id
                port_bind = int(listener.config.get("port_bind", port_bind))

        if profile is None:
            return

        chain = await self.get_asset_chain(chain_asset_id)
        validate_profile_compatibility(profile, chain, port_bind=port_bind)

    async def _create_replacement_asset(
        self,
        asset: InfrastructureAssetData,
        run_id: str,
    ) -> InfrastructureAssetData:
        now = datetime.now(UTC)
        replacement = asset.model_copy(
            update={
                "asset_id": uuid4().hex,
                "name": f"{asset.name}-rotated-{run_id[:6]}",
                "health": InfraHealthStatus.UNKNOWN,
                "rendered_checksum": "",
                "last_deployment_run_id": "",
                "dns_state": "planned_rotation",
                "create_time": now,
                "update_time": now,
            }
        )
        await self._db.infrastructure_asset_insert(replacement)
        return replacement

    async def _flip_rotation(
        self,
        original: InfrastructureAssetData,
        replacement: InfrastructureAssetData,
        run: DeploymentRunData,
    ) -> None:
        assets = await self._db.infrastructure_asset_list()
        child_ids: list[str] = []
        for asset in assets:
            updates = {}
            if asset.parent_asset_id == original.asset_id:
                updates["parent_asset_id"] = replacement.asset_id
                child_ids.append(asset.asset_id)
            if original.asset_id in asset.upstream_asset_ids:
                updates["upstream_asset_ids"] = [
                    replacement.asset_id if item == original.asset_id else item
                    for item in asset.upstream_asset_ids
                ]
            if original.asset_id in asset.downstream_asset_ids:
                updates["downstream_asset_ids"] = [
                    replacement.asset_id if item == original.asset_id else item
                    for item in asset.downstream_asset_ids
                ]
            if updates:
                updates["update_time"] = datetime.now(UTC)
                await self._db.infrastructure_asset_update(asset.asset_id, **updates)

        await self._db.infrastructure_asset_update(
            replacement.asset_id,
            downstream_asset_ids=child_ids,
            update_time=datetime.now(UTC),
        )
        rollback = dict(run.rollback_data)
        rollback["child_asset_ids"] = child_ids
        await self._db.deployment_run_update(run.run_id, rollback_data=rollback)

    async def _render_artifacts(
        self,
        asset: InfrastructureAssetData,
        run_id: str,
        target: DeployTarget,
        operation: str,
    ) -> RenderedArtifacts:
        artifact_dir = self._root / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "run_id": run_id,
            "asset_id": asset.asset_id,
            "asset_name": asset.name,
            "asset_type": asset.asset_type.value,
            "target": target.value,
            "operation": operation,
            "dns_records": [{"hostname": asset.config.get("hostname", asset.name)}],
        }
        files: dict[str, str] = {
            "manifest.json": json.dumps(manifest, indent=2, sort_keys=True),
            "nginx.redirector.conf": self._render_nginx(asset),
        }
        if target is DeployTarget.DOCKER_COMPOSE:
            files["docker-compose.generated.yaml"] = yaml.safe_dump(
                {
                    "services": {
                        asset.name.replace(".", "-"): {
                            "image": "nginx:stable",
                            "ports": [f"{asset.config.get('listen_port', 443)}:443"],
                        }
                    }
                },
                sort_keys=False,
            )
        else:
            files["main.tf.json"] = json.dumps(
                {
                    "resource": {
                        "null_resource": {
                            asset.name.replace(".", "_"): {"triggers": {"asset_id": asset.asset_id}}
                        }
                    }
                },
                indent=2,
                sort_keys=True,
            )

        checksums: dict[str, str] = {}
        for filename, content in files.items():
            path = artifact_dir / filename
            path.write_text(content)
            checksums[filename] = hashlib.sha256(content.encode()).hexdigest()
        return RenderedArtifacts(
            artifact_dir=artifact_dir, manifest=manifest, files=files, checksums=checksums
        )

    def _render_nginx(self, asset: InfrastructureAssetData) -> str:
        hostname = asset.config.get("hostname", asset.name)
        listen_port = int(asset.config.get("listen_port", 443))
        return (
            "server {\n"
            f"    listen {listen_port} ssl;\n"
            f"    server_name {hostname};\n"
            "    location / {\n"
            "        proxy_pass http://127.0.0.1:4321;\n"
            "    }\n"
            "}\n"
        )
