"""aiosqlite database layer for ExecuteC2."""

import calendar
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from executec2.server import secrets as secretlib
from executec2.server.models import (
    AgentData,
    AgentMark,
    ChatMessage,
    CredentialData,
    CredentialType,
    DeploymentRunData,
    DeploymentRunStatus,
    DeployTarget,
    DownloadData,
    DownloadState,
    InfraHealthSnapshotData,
    InfraHealthStatus,
    InfraStage,
    InfrastructureAssetData,
    InfrastructureAssetType,
    ListenerData,
    ListenerStatus,
    MessageType,
    OSType,
    TargetData,
    TaskData,
    TaskType,
    TrafficProfileData,
    TrafficProfileKind,
    TrafficProfileTLSMode,
    TunnelData,
    TunnelType,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listeners (
    listener_name TEXT PRIMARY KEY,
    listener_type TEXT NOT NULL,
    config        TEXT NOT NULL,
    traffic_profile_id TEXT NOT NULL DEFAULT '',
    ingress_asset_id   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'stopped',
    create_time   INTEGER NOT NULL,
    watermark     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS traffic_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    listener_type TEXT NOT NULL,
    stage INTEGER NOT NULL,
    profile_kind TEXT NOT NULL,
    callback_hostnames TEXT NOT NULL DEFAULT '[]',
    uris TEXT NOT NULL DEFAULT '[]',
    http_method TEXT NOT NULL DEFAULT 'POST',
    user_agents TEXT NOT NULL DEFAULT '[]',
    host_headers TEXT NOT NULL DEFAULT '[]',
    request_headers TEXT NOT NULL DEFAULT '{}',
    response_headers TEXT NOT NULL DEFAULT '{}',
    trust_x_forwarded_for BOOLEAN NOT NULL DEFAULT 0,
    page_error TEXT NOT NULL DEFAULT '',
    page_payload TEXT NOT NULL DEFAULT '',
    tls_mode TEXT NOT NULL DEFAULT 'optional',
    source_listener TEXT NOT NULL DEFAULT '',
    create_time INTEGER NOT NULL,
    update_time INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS infrastructure_assets (
    asset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    stage INTEGER NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    parent_asset_id TEXT NOT NULL DEFAULT '',
    linked_listener_name TEXT NOT NULL DEFAULT '',
    traffic_profile_id TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    config TEXT NOT NULL DEFAULT '{}',
    deploy_target TEXT NOT NULL DEFAULT 'docker_compose',
    health TEXT NOT NULL DEFAULT 'unknown',
    dns_state TEXT NOT NULL DEFAULT '',
    certificate_expires_at INTEGER,
    upstream_asset_ids TEXT NOT NULL DEFAULT '[]',
    downstream_asset_ids TEXT NOT NULL DEFAULT '[]',
    stage_owner TEXT NOT NULL DEFAULT '',
    rendered_checksum TEXT NOT NULL DEFAULT '',
    last_deployment_run_id TEXT NOT NULL DEFAULT '',
    last_health_observed_at INTEGER,
    create_time INTEGER NOT NULL,
    update_time INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS deployment_runs (
    run_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    artifact_dir TEXT NOT NULL DEFAULT '',
    plan_data TEXT NOT NULL DEFAULT '{}',
    provider_responses TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    failure_reason TEXT NOT NULL DEFAULT '',
    failure_phase TEXT NOT NULL DEFAULT '',
    backend_commands TEXT NOT NULL DEFAULT '[]',
    execution_log TEXT NOT NULL DEFAULT '[]',
    health_checks TEXT NOT NULL DEFAULT '[]',
    rollback_data TEXT NOT NULL DEFAULT '{}',
    replacement_asset_id TEXT NOT NULL DEFAULT '',
    started_at INTEGER,
    finished_at INTEGER,
    timeout_seconds INTEGER NOT NULL DEFAULT 90,
    create_time INTEGER NOT NULL,
    update_time INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS infra_health_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '{}',
    observed_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    session_key  BLOB NOT NULL,
    listener     TEXT NOT NULL,
    external_ip  TEXT NOT NULL DEFAULT '',
    internal_ip  TEXT NOT NULL DEFAULT '',
    gmt_offset   INTEGER NOT NULL DEFAULT 0,
    sleep        INTEGER NOT NULL DEFAULT 60,
    jitter       INTEGER NOT NULL DEFAULT 0,
    pid          INTEGER NOT NULL DEFAULT 0,
    tid          INTEGER NOT NULL DEFAULT 0,
    arch         TEXT NOT NULL DEFAULT '',
    elevated     BOOLEAN NOT NULL DEFAULT 0,
    process      TEXT NOT NULL DEFAULT '',
    os           INTEGER NOT NULL DEFAULT 2,
    os_desc      TEXT NOT NULL DEFAULT '',
    domain       TEXT NOT NULL DEFAULT '',
    computer     TEXT NOT NULL DEFAULT '',
    username     TEXT NOT NULL DEFAULT '',
    create_time  INTEGER NOT NULL,
    last_tick    INTEGER NOT NULL,
    kill_date    TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '',
    mark         TEXT NOT NULL DEFAULT '',
    color        TEXT NOT NULL DEFAULT '',
    target_id    TEXT NOT NULL DEFAULT '',
    custom_data  BLOB NOT NULL DEFAULT x'',
    last_counter INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id      TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL,
    task_type    INTEGER NOT NULL DEFAULT 0,
    client       TEXT NOT NULL DEFAULT '',
    start_date   INTEGER NOT NULL,
    finish_date  INTEGER,
    command_line TEXT NOT NULL DEFAULT '',
    message_type INTEGER NOT NULL DEFAULT 0,
    message      TEXT NOT NULL DEFAULT '',
    clear_text   TEXT NOT NULL DEFAULT '',
    completed    BOOLEAN NOT NULL DEFAULT 0,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS consoles (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    packet   BLOB NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS downloads (
    file_id     TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    agent_name  TEXT NOT NULL DEFAULT '',
    user        TEXT NOT NULL DEFAULT '',
    computer    TEXT NOT NULL DEFAULT '',
    remote_path TEXT NOT NULL,
    local_path  TEXT NOT NULL DEFAULT '',
    total_size  INTEGER NOT NULL DEFAULT 0,
    recv_size   INTEGER NOT NULL DEFAULT 0,
    date        INTEGER NOT NULL,
    state       INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS credentials (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    cred_id   TEXT NOT NULL UNIQUE,
    username  TEXT NOT NULL DEFAULT '',
    secret    BLOB NOT NULL DEFAULT x'',
    realm     TEXT NOT NULL DEFAULT '',
    cred_type TEXT NOT NULL DEFAULT 'password',
    tag       TEXT NOT NULL DEFAULT '',
    date      INTEGER NOT NULL,
    source    TEXT NOT NULL DEFAULT '',
    agent_id  TEXT NOT NULL DEFAULT '',
    host      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS targets (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT NOT NULL UNIQUE,
    computer  TEXT NOT NULL DEFAULT '',
    domain    TEXT NOT NULL DEFAULT '',
    address   TEXT NOT NULL DEFAULT '',
    os        TEXT NOT NULL DEFAULT '',
    os_desc   TEXT NOT NULL DEFAULT '',
    tag       TEXT NOT NULL DEFAULT '',
    info      TEXT NOT NULL DEFAULT '',
    date      INTEGER NOT NULL,
    alive     BOOLEAN NOT NULL DEFAULT 1,
    agents    TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS tunnels (
    tunnel_id   TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    tunnel_type TEXT NOT NULL,
    info        TEXT NOT NULL DEFAULT '',
    lhost       TEXT NOT NULL DEFAULT '127.0.0.1',
    lport       INTEGER NOT NULL,
    thost       TEXT NOT NULL DEFAULT '',
    tport       INTEGER NOT NULL DEFAULT 0,
    use_auth    BOOLEAN NOT NULL DEFAULT 0,
    username    TEXT NOT NULL DEFAULT '',
    password    TEXT NOT NULL DEFAULT '',
    create_time INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS chat (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    message  TEXT NOT NULL,
    date     INTEGER NOT NULL
);
"""


def _ts(dt: datetime) -> int:
    """Convert naive UTC datetime to Unix timestamp."""
    return calendar.timegm(dt.timetuple())


def _dt(ts: int) -> datetime:
    """Convert Unix timestamp to timezone-aware UTC datetime."""
    return datetime.fromtimestamp(ts, UTC)


def _maybe_ts(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    return _ts(dt)


def _maybe_dt(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return _dt(ts)


class Database:
    def __init__(self, conn: aiosqlite.Connection, secret_context=None):
        self._conn = conn
        self._secret_context = secret_context

    @classmethod
    async def create(cls, db_path: str | Path, secret_context=None) -> "Database":
        conn = await aiosqlite.connect(str(db_path))
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA busy_timeout=10000")
        await conn.execute("PRAGMA cache_size=-64000")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.commit()
        db = cls(conn, secret_context=secret_context)
        await db.migrate()
        return db

    async def migrate(self) -> None:
        await self._conn.executescript(_SCHEMA)
        await self._ensure_column("agents", "last_counter", "INTEGER NOT NULL DEFAULT 0")
        await self._ensure_column("listeners", "traffic_profile_id", "TEXT NOT NULL DEFAULT ''")
        await self._ensure_column("listeners", "ingress_asset_id", "TEXT NOT NULL DEFAULT ''")
        await self._ensure_column("infrastructure_assets", "dns_state", "TEXT NOT NULL DEFAULT ''")
        await self._ensure_column("infrastructure_assets", "certificate_expires_at", "INTEGER")
        await self._ensure_column(
            "infrastructure_assets", "upstream_asset_ids", "TEXT NOT NULL DEFAULT '[]'"
        )
        await self._ensure_column(
            "infrastructure_assets", "downstream_asset_ids", "TEXT NOT NULL DEFAULT '[]'"
        )
        await self._ensure_column(
            "infrastructure_assets", "stage_owner", "TEXT NOT NULL DEFAULT ''"
        )
        await self._ensure_column("infrastructure_assets", "last_health_observed_at", "INTEGER")
        await self._ensure_column("deployment_runs", "failure_reason", "TEXT NOT NULL DEFAULT ''")
        await self._ensure_column("deployment_runs", "failure_phase", "TEXT NOT NULL DEFAULT ''")
        await self._ensure_column(
            "deployment_runs", "backend_commands", "TEXT NOT NULL DEFAULT '[]'"
        )
        await self._ensure_column("deployment_runs", "execution_log", "TEXT NOT NULL DEFAULT '[]'")
        await self._ensure_column("deployment_runs", "health_checks", "TEXT NOT NULL DEFAULT '[]'")
        await self._ensure_column("deployment_runs", "rollback_data", "TEXT NOT NULL DEFAULT '{}'")
        await self._ensure_column("deployment_runs", "started_at", "INTEGER")
        await self._ensure_column("deployment_runs", "finished_at", "INTEGER")
        await self._ensure_column(
            "deployment_runs", "timeout_seconds", "INTEGER NOT NULL DEFAULT 90"
        )
        await self._conn.commit()

    async def _ensure_column(self, table: str, column: str, ddl_fragment: str) -> None:
        async with self._conn.execute(f"PRAGMA table_info({table})") as cur:
            rows = await cur.fetchall()
        if any(r["name"] == column for r in rows):
            return
        await self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_fragment}")

    async def migrate_secrets(self) -> None:
        if self._secret_context is None:
            return

        await self._conn.execute(
            "INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('secrets_migrated', '0')"
        )
        await self._conn.commit()

        async with self._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'secrets_migrated'"
        ) as cur:
            row = await cur.fetchone()
        if row and row["value"] == "1":
            return

        async with self._conn.execute("SELECT id, session_key FROM agents") as cur:
            agents = await cur.fetchall()
        for row in agents:
            raw = bytes(row["session_key"])
            if secretlib.is_envelope(raw):
                continue
            wrapped = secretlib.encrypt_envelope(self._secret_context.session_wrap_key, raw)
            await self._conn.execute(
                "UPDATE agents SET session_key = ? WHERE id = ?",
                (wrapped, row["id"]),
            )

        async with self._conn.execute("SELECT cred_id, secret FROM credentials") as cur:
            creds = await cur.fetchall()
        for row in creds:
            blob = bytes(row["secret"])
            if not blob:
                continue
            if secretlib.is_envelope(blob):
                continue
            plaintext: bytes | None = None
            try:
                plaintext = secretlib.decrypt_legacy_aesgcm(
                    self._secret_context.legacy_credential_key,
                    blob,
                )
            except Exception:
                plaintext = None
            if plaintext is None:
                # Preserve unreadable legacy rows as-is.
                continue
            wrapped = secretlib.encrypt_envelope(self._secret_context.credential_key, plaintext)
            await self._conn.execute(
                "UPDATE credentials SET secret = ? WHERE cred_id = ?",
                (wrapped, row["cred_id"]),
            )

        await self._conn.execute(
            "UPDATE schema_meta SET value = '1' WHERE key = 'secrets_migrated'"
        )
        await self._conn.commit()

    async def close(self) -> None:
        await self._conn.close()

    def _encrypt_session_key(self, raw: bytes) -> bytes:
        if self._secret_context is None:
            return raw
        return secretlib.encrypt_envelope(self._secret_context.session_wrap_key, raw)

    def _decrypt_session_key(self, blob: bytes) -> bytes:
        if self._secret_context is None:
            return blob
        if secretlib.is_envelope(blob):
            return secretlib.decrypt_envelope(self._secret_context.session_wrap_key, blob)
        return blob

    def _encrypt_credential_secret(self, plaintext: str) -> bytes:
        if not plaintext:
            return b""
        data = plaintext.encode("utf-8")
        if self._secret_context is None:
            return data
        return secretlib.encrypt_envelope(self._secret_context.credential_key, data)

    def _decrypt_credential_secret(self, blob: bytes) -> str:
        if not blob:
            return ""
        if self._secret_context is None:
            return blob.decode("utf-8", errors="replace")
        try:
            if secretlib.is_envelope(blob):
                return secretlib.decrypt_envelope(
                    self._secret_context.credential_key,
                    blob,
                ).decode("utf-8", errors="replace")
            return secretlib.decrypt_legacy_aesgcm(
                self._secret_context.legacy_credential_key,
                blob,
            ).decode("utf-8", errors="replace")
        except Exception:
            return ""

    # -----------------------------------------------------------------------
    # Listener CRUD
    # -----------------------------------------------------------------------

    async def listener_insert(self, data: ListenerData) -> None:
        await self._conn.execute(
            "INSERT INTO listeners (listener_name, listener_type, config, traffic_profile_id,"
            " ingress_asset_id, status, create_time, watermark)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.listener_name,
                data.listener_type,
                json.dumps(data.config),
                data.traffic_profile_id,
                data.ingress_asset_id,
                data.status.value,
                _ts(data.create_time),
                data.watermark,
            ),
        )
        await self._conn.commit()

    async def listener_get(self, name: str) -> ListenerData | None:
        async with self._conn.execute(
            "SELECT * FROM listeners WHERE listener_name = ?", (name,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return ListenerData(
            listener_name=row["listener_name"],
            listener_type=row["listener_type"],
            config=json.loads(row["config"]),
            traffic_profile_id=row["traffic_profile_id"],
            ingress_asset_id=row["ingress_asset_id"],
            status=ListenerStatus(row["status"]),
            create_time=_dt(row["create_time"]),
            watermark=row["watermark"],
        )

    async def listener_list(self) -> list[ListenerData]:
        async with self._conn.execute("SELECT * FROM listeners") as cur:
            rows = await cur.fetchall()
        return [
            ListenerData(
                listener_name=r["listener_name"],
                listener_type=r["listener_type"],
                config=json.loads(r["config"]),
                traffic_profile_id=r["traffic_profile_id"],
                ingress_asset_id=r["ingress_asset_id"],
                status=ListenerStatus(r["status"]),
                create_time=_dt(r["create_time"]),
                watermark=r["watermark"],
            )
            for r in rows
        ]

    async def listener_update(self, name: str, **fields: Any) -> None:
        _col_map = {
            "status": "status",
            "config": "config",
            "watermark": "watermark",
            "traffic_profile_id": "traffic_profile_id",
            "ingress_asset_id": "ingress_asset_id",
        }
        sets, vals = [], []
        for k, v in fields.items():
            col = _col_map.get(k, k)
            if col == "config":
                v = json.dumps(v)
            elif hasattr(v, "value"):
                v = v.value
            sets.append(f"{col} = ?")
            vals.append(v)
        vals.append(name)
        await self._conn.execute(
            f"UPDATE listeners SET {', '.join(sets)} WHERE listener_name = ?", vals
        )
        await self._conn.commit()

    async def listener_delete(self, name: str) -> None:
        await self._conn.execute("DELETE FROM listeners WHERE listener_name = ?", (name,))
        await self._conn.commit()

    # -----------------------------------------------------------------------
    # Traffic profile CRUD
    # -----------------------------------------------------------------------

    def _row_to_traffic_profile(self, row: aiosqlite.Row) -> TrafficProfileData:
        return TrafficProfileData(
            profile_id=row["profile_id"],
            name=row["name"],
            listener_type=row["listener_type"],
            stage=InfraStage(row["stage"]),
            profile_kind=TrafficProfileKind(row["profile_kind"]),
            callback_hostnames=json.loads(row["callback_hostnames"]),
            uris=json.loads(row["uris"]),
            http_method=row["http_method"],
            user_agents=json.loads(row["user_agents"]),
            host_headers=json.loads(row["host_headers"]),
            request_headers=json.loads(row["request_headers"]),
            response_headers=json.loads(row["response_headers"]),
            trust_x_forwarded_for=bool(row["trust_x_forwarded_for"]),
            page_error=row["page_error"],
            page_payload=row["page_payload"],
            tls_mode=TrafficProfileTLSMode(row["tls_mode"]),
            source_listener=row["source_listener"],
            create_time=_dt(row["create_time"]),
            update_time=_dt(row["update_time"]),
        )

    async def traffic_profile_insert(self, data: TrafficProfileData) -> None:
        await self._conn.execute(
            "INSERT INTO traffic_profiles (profile_id, name, listener_type, stage, profile_kind,"
            " callback_hostnames, uris, http_method, user_agents, host_headers, request_headers,"
            " response_headers, trust_x_forwarded_for, page_error, page_payload, tls_mode,"
            " source_listener, create_time, update_time)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.profile_id,
                data.name,
                data.listener_type,
                int(data.stage),
                data.profile_kind.value,
                json.dumps(data.callback_hostnames),
                json.dumps(data.uris),
                data.http_method,
                json.dumps(data.user_agents),
                json.dumps(data.host_headers),
                json.dumps(data.request_headers),
                json.dumps(data.response_headers),
                int(data.trust_x_forwarded_for),
                data.page_error,
                data.page_payload,
                data.tls_mode.value,
                data.source_listener,
                _ts(data.create_time),
                _ts(data.update_time),
            ),
        )
        await self._conn.commit()

    async def traffic_profile_get(self, profile_id: str) -> TrafficProfileData | None:
        async with self._conn.execute(
            "SELECT * FROM traffic_profiles WHERE profile_id = ?",
            (profile_id,),
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_traffic_profile(row) if row else None

    async def traffic_profile_list(self) -> list[TrafficProfileData]:
        async with self._conn.execute("SELECT * FROM traffic_profiles ORDER BY create_time") as cur:
            rows = await cur.fetchall()
        return [self._row_to_traffic_profile(row) for row in rows]

    async def traffic_profile_update(self, profile_id: str, **fields: Any) -> None:
        json_fields = {
            "callback_hostnames",
            "uris",
            "user_agents",
            "host_headers",
            "request_headers",
            "response_headers",
        }
        sets, vals = [], []
        for key, value in fields.items():
            if key in json_fields:
                value = json.dumps(value)
            elif key == "trust_x_forwarded_for":
                value = int(bool(value))
            elif isinstance(value, datetime):
                value = _ts(value)
            elif hasattr(value, "value"):
                value = value.value
            sets.append(f"{key} = ?")
            vals.append(value)
        vals.append(profile_id)
        await self._conn.execute(
            f"UPDATE traffic_profiles SET {', '.join(sets)} WHERE profile_id = ?",
            vals,
        )
        await self._conn.commit()

    async def traffic_profile_delete(self, profile_id: str) -> None:
        await self._conn.execute("DELETE FROM traffic_profiles WHERE profile_id = ?", (profile_id,))
        await self._conn.commit()

    # -----------------------------------------------------------------------
    # Infrastructure asset CRUD
    # -----------------------------------------------------------------------

    def _row_to_infrastructure_asset(self, row: aiosqlite.Row) -> InfrastructureAssetData:
        return InfrastructureAssetData(
            asset_id=row["asset_id"],
            name=row["name"],
            asset_type=InfrastructureAssetType(row["asset_type"]),
            stage=InfraStage(row["stage"]),
            provider=row["provider"],
            parent_asset_id=row["parent_asset_id"],
            linked_listener_name=row["linked_listener_name"],
            traffic_profile_id=row["traffic_profile_id"],
            owner=row["owner"],
            tags=json.loads(row["tags"]),
            config=json.loads(row["config"]),
            deploy_target=DeployTarget(row["deploy_target"]),
            health=InfraHealthStatus(row["health"]),
            dns_state=row["dns_state"],
            certificate_expires_at=_maybe_dt(row["certificate_expires_at"]),
            upstream_asset_ids=json.loads(row["upstream_asset_ids"]),
            downstream_asset_ids=json.loads(row["downstream_asset_ids"]),
            stage_owner=row["stage_owner"],
            rendered_checksum=row["rendered_checksum"],
            last_deployment_run_id=row["last_deployment_run_id"],
            last_health_observed_at=_maybe_dt(row["last_health_observed_at"]),
            create_time=_dt(row["create_time"]),
            update_time=_dt(row["update_time"]),
        )

    async def infrastructure_asset_insert(self, data: InfrastructureAssetData) -> None:
        await self._conn.execute(
            "INSERT INTO infrastructure_assets ("
            "asset_id, name, asset_type, stage, provider, parent_asset_id, "
            "linked_listener_name, traffic_profile_id, owner, tags, config, "
            "deploy_target, health, dns_state, certificate_expires_at, upstream_asset_ids, "
            "downstream_asset_ids, stage_owner, rendered_checksum, last_deployment_run_id, "
            "last_health_observed_at, create_time, update_time)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.asset_id,
                data.name,
                data.asset_type.value,
                int(data.stage),
                data.provider,
                data.parent_asset_id,
                data.linked_listener_name,
                data.traffic_profile_id,
                data.owner,
                json.dumps(data.tags),
                json.dumps(data.config),
                data.deploy_target.value,
                data.health.value,
                data.dns_state,
                _maybe_ts(data.certificate_expires_at),
                json.dumps(data.upstream_asset_ids),
                json.dumps(data.downstream_asset_ids),
                data.stage_owner,
                data.rendered_checksum,
                data.last_deployment_run_id,
                _maybe_ts(data.last_health_observed_at),
                _ts(data.create_time),
                _ts(data.update_time),
            ),
        )
        await self._conn.commit()

    async def infrastructure_asset_get(self, asset_id: str) -> InfrastructureAssetData | None:
        async with self._conn.execute(
            "SELECT * FROM infrastructure_assets WHERE asset_id = ?",
            (asset_id,),
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_infrastructure_asset(row) if row else None

    async def infrastructure_asset_list(
        self,
        *,
        stage: InfraStage | None = None,
        asset_type: InfrastructureAssetType | None = None,
    ) -> list[InfrastructureAssetData]:
        query = "SELECT * FROM infrastructure_assets"
        clauses = []
        vals: list[Any] = []
        if stage is not None:
            clauses.append("stage = ?")
            vals.append(int(stage))
        if asset_type is not None:
            clauses.append("asset_type = ?")
            vals.append(asset_type.value)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY create_time"
        async with self._conn.execute(query, vals) as cur:
            rows = await cur.fetchall()
        return [self._row_to_infrastructure_asset(row) for row in rows]

    async def infrastructure_asset_update(self, asset_id: str, **fields: Any) -> None:
        json_fields = {"tags", "config", "upstream_asset_ids", "downstream_asset_ids"}
        sets, vals = [], []
        for key, value in fields.items():
            if key in json_fields:
                value = json.dumps(value)
            elif isinstance(value, datetime):
                value = _ts(value)
            elif value is None and key in {"certificate_expires_at", "last_health_observed_at"}:
                value = None
            elif hasattr(value, "value"):
                value = value.value
            sets.append(f"{key} = ?")
            vals.append(value)
        vals.append(asset_id)
        await self._conn.execute(
            f"UPDATE infrastructure_assets SET {', '.join(sets)} WHERE asset_id = ?",
            vals,
        )
        await self._conn.commit()

    async def infrastructure_asset_delete(self, asset_id: str) -> None:
        await self._conn.execute(
            "DELETE FROM infrastructure_assets WHERE asset_id = ?", (asset_id,)
        )
        await self._conn.commit()

    # -----------------------------------------------------------------------
    # Deployment run CRUD
    # -----------------------------------------------------------------------

    def _row_to_deployment_run(self, row: aiosqlite.Row) -> DeploymentRunData:
        return DeploymentRunData(
            run_id=row["run_id"],
            asset_id=row["asset_id"],
            operation=row["operation"],
            target=DeployTarget(row["target"]),
            status=DeploymentRunStatus(row["status"]),
            created_by=row["created_by"],
            artifact_dir=row["artifact_dir"],
            plan_data=json.loads(row["plan_data"]),
            provider_responses=json.loads(row["provider_responses"]),
            error=row["error"],
            failure_reason=row["failure_reason"],
            failure_phase=row["failure_phase"],
            backend_commands=json.loads(row["backend_commands"]),
            execution_log=json.loads(row["execution_log"]),
            health_checks=json.loads(row["health_checks"]),
            rollback_data=json.loads(row["rollback_data"]),
            replacement_asset_id=row["replacement_asset_id"],
            started_at=_maybe_dt(row["started_at"]),
            finished_at=_maybe_dt(row["finished_at"]),
            timeout_seconds=row["timeout_seconds"],
            create_time=_dt(row["create_time"]),
            update_time=_dt(row["update_time"]),
        )

    async def deployment_run_insert(self, data: DeploymentRunData) -> None:
        await self._conn.execute(
            "INSERT INTO deployment_runs ("
            "run_id, asset_id, operation, target, status, created_by, artifact_dir, "
            "plan_data, provider_responses, error, failure_reason, failure_phase, "
            "backend_commands, execution_log, health_checks, rollback_data, "
            "replacement_asset_id, started_at, finished_at, timeout_seconds, "
            "create_time, update_time)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.run_id,
                data.asset_id,
                data.operation,
                data.target.value,
                data.status.value,
                data.created_by,
                data.artifact_dir,
                json.dumps(data.plan_data),
                json.dumps(data.provider_responses),
                data.error,
                data.failure_reason,
                data.failure_phase,
                json.dumps(data.backend_commands),
                json.dumps(data.execution_log),
                json.dumps(data.health_checks),
                json.dumps(data.rollback_data),
                data.replacement_asset_id,
                _maybe_ts(data.started_at),
                _maybe_ts(data.finished_at),
                data.timeout_seconds,
                _ts(data.create_time),
                _ts(data.update_time),
            ),
        )
        await self._conn.commit()

    async def deployment_run_get(self, run_id: str) -> DeploymentRunData | None:
        async with self._conn.execute(
            "SELECT * FROM deployment_runs WHERE run_id = ?",
            (run_id,),
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_deployment_run(row) if row else None

    async def deployment_run_list(
        self,
        asset_id: str | None = None,
        status: DeploymentRunStatus | None = None,
        operation: str | None = None,
        target: DeployTarget | None = None,
    ) -> list[DeploymentRunData]:
        query = "SELECT * FROM deployment_runs"
        clauses = []
        vals: list[Any] = []
        if asset_id:
            clauses.append("asset_id = ?")
            vals.append(asset_id)
        if status is not None:
            clauses.append("status = ?")
            vals.append(status.value)
        if operation:
            clauses.append("operation = ?")
            vals.append(operation)
        if target is not None:
            clauses.append("target = ?")
            vals.append(target.value)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY create_time"
        async with self._conn.execute(query, vals) as cur:
            rows = await cur.fetchall()
        return [self._row_to_deployment_run(row) for row in rows]

    async def deployment_run_update(self, run_id: str, **fields: Any) -> None:
        json_fields = {
            "plan_data",
            "provider_responses",
            "backend_commands",
            "execution_log",
            "health_checks",
            "rollback_data",
        }
        sets, vals = [], []
        for key, value in fields.items():
            if key in json_fields:
                value = json.dumps(value)
            elif isinstance(value, datetime):
                value = _ts(value)
            elif value is None and key in {"started_at", "finished_at"}:
                value = None
            elif hasattr(value, "value"):
                value = value.value
            sets.append(f"{key} = ?")
            vals.append(value)
        vals.append(run_id)
        await self._conn.execute(
            f"UPDATE deployment_runs SET {', '.join(sets)} WHERE run_id = ?",
            vals,
        )
        await self._conn.commit()

    async def deployment_run_delete(self, run_id: str) -> None:
        await self._conn.execute("DELETE FROM deployment_runs WHERE run_id = ?", (run_id,))
        await self._conn.commit()

    # -----------------------------------------------------------------------
    # Infra health snapshots
    # -----------------------------------------------------------------------

    def _row_to_health_snapshot(self, row: aiosqlite.Row) -> InfraHealthSnapshotData:
        return InfraHealthSnapshotData(
            snapshot_id=row["snapshot_id"],
            asset_id=row["asset_id"],
            status=InfraHealthStatus(row["status"]),
            summary=row["summary"],
            details=json.loads(row["details"]),
            observed_at=_dt(row["observed_at"]),
        )

    async def infra_health_snapshot_insert(self, data: InfraHealthSnapshotData) -> None:
        await self._conn.execute(
            "INSERT INTO infra_health_snapshots ("
            "snapshot_id, asset_id, status, summary, details, observed_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                data.snapshot_id,
                data.asset_id,
                data.status.value,
                data.summary,
                json.dumps(data.details),
                _ts(data.observed_at),
            ),
        )
        await self._conn.commit()

    async def infra_health_snapshot_list(
        self, asset_id: str | None = None
    ) -> list[InfraHealthSnapshotData]:
        query = "SELECT * FROM infra_health_snapshots"
        vals: list[Any] = []
        if asset_id:
            query += " WHERE asset_id = ?"
            vals.append(asset_id)
        query += " ORDER BY observed_at"
        async with self._conn.execute(query, vals) as cur:
            rows = await cur.fetchall()
        return [self._row_to_health_snapshot(row) for row in rows]

    # -----------------------------------------------------------------------
    # Agent CRUD
    # -----------------------------------------------------------------------

    async def agent_insert(self, data: AgentData) -> None:
        await self._conn.execute(
            "INSERT INTO agents (id, name, session_key, listener, external_ip, internal_ip,"
            " gmt_offset, sleep, jitter, pid, tid, arch, elevated, process, os, os_desc,"
            " domain, computer, username, create_time, last_tick, kill_date, tags, mark,"
            " color, target_id, custom_data, last_counter)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data.id,
                data.name,
                self._encrypt_session_key(data.session_key),
                data.listener,
                data.external_ip,
                data.internal_ip,
                data.gmt_offset,
                data.sleep,
                data.jitter,
                data.pid,
                data.tid,
                data.arch,
                int(data.elevated),
                data.process,
                int(data.os),
                data.os_desc,
                data.domain,
                data.computer,
                data.username,
                _ts(data.create_time),
                _ts(data.last_tick),
                data.kill_date,
                data.tags,
                data.mark.value,
                data.color,
                data.target_id,
                data.custom_data,
                data.last_counter,
            ),
        )
        await self._conn.commit()

    def _row_to_agent(self, row: aiosqlite.Row) -> AgentData:
        return AgentData(
            id=row["id"],
            name=row["name"],
            session_key=self._decrypt_session_key(bytes(row["session_key"])),
            listener=row["listener"],
            external_ip=row["external_ip"],
            internal_ip=row["internal_ip"],
            gmt_offset=row["gmt_offset"],
            sleep=row["sleep"],
            jitter=row["jitter"],
            pid=row["pid"],
            tid=row["tid"],
            arch=row["arch"],
            elevated=bool(row["elevated"]),
            process=row["process"],
            os=OSType(row["os"]),
            os_desc=row["os_desc"],
            domain=row["domain"],
            computer=row["computer"],
            username=row["username"],
            create_time=_dt(row["create_time"]),
            last_tick=_dt(row["last_tick"]),
            kill_date=row["kill_date"],
            tags=row["tags"],
            mark=AgentMark(row["mark"]),
            color=row["color"],
            target_id=row["target_id"],
            custom_data=bytes(row["custom_data"]),
            last_counter=row["last_counter"],
        )

    async def agent_get(self, agent_id: str) -> AgentData | None:
        async with self._conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)) as cur:
            row = await cur.fetchone()
        return self._row_to_agent(row) if row else None

    async def agent_list(self) -> list[AgentData]:
        async with self._conn.execute("SELECT * FROM agents") as cur:
            rows = await cur.fetchall()
        return [self._row_to_agent(r) for r in rows]

    async def agent_update(self, agent_id: str, **fields: Any) -> None:
        _col_map = {
            "mark": "mark",
            "last_tick": "last_tick",
            "color": "color",
            "tags": "tags",
            "sleep": "sleep",
            "jitter": "jitter",
            "target_id": "target_id",
            "custom_data": "custom_data",
        }
        sets, vals = [], []
        for k, v in fields.items():
            col = _col_map.get(k, k)
            if col == "last_tick" and isinstance(v, datetime):
                v = _ts(v)
            elif col == "session_key":
                v = self._encrypt_session_key(v)
            elif hasattr(v, "value"):
                v = v.value
            sets.append(f"{col} = ?")
            vals.append(v)
        vals.append(agent_id)
        await self._conn.execute(f"UPDATE agents SET {', '.join(sets)} WHERE id = ?", vals)
        await self._conn.commit()

    async def agent_delete(self, agent_id: str) -> None:
        await self._conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        await self._conn.commit()

    # -----------------------------------------------------------------------
    # Task CRUD
    # -----------------------------------------------------------------------

    async def task_insert(self, data: TaskData) -> None:
        finish_ts = _ts(data.finish_date) if data.finish_date else None
        await self._conn.execute(
            "INSERT INTO tasks (task_id, agent_id, task_type, client, start_date, finish_date,"
            " command_line, message_type, message, clear_text, completed)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                data.task_id,
                data.agent_id,
                int(data.task_type),
                data.client,
                _ts(data.start_date),
                finish_ts,
                data.command_line,
                int(data.message_type),
                data.message,
                data.clear_text,
                int(data.completed),
            ),
        )
        await self._conn.commit()

    def _row_to_task(self, row: aiosqlite.Row) -> TaskData:
        return TaskData(
            task_id=row["task_id"],
            agent_id=row["agent_id"],
            task_type=TaskType(row["task_type"]),
            client=row["client"],
            start_date=_dt(row["start_date"]),
            finish_date=_dt(row["finish_date"]) if row["finish_date"] else None,
            command_line=row["command_line"],
            message_type=MessageType(row["message_type"]),
            message=row["message"],
            clear_text=row["clear_text"],
            completed=bool(row["completed"]),
        )

    async def task_get(self, task_id: str) -> TaskData | None:
        async with self._conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)) as cur:
            row = await cur.fetchone()
        return self._row_to_task(row) if row else None

    async def task_list(self, agent_id: str) -> list[TaskData]:
        async with self._conn.execute(
            "SELECT * FROM tasks WHERE agent_id = ? ORDER BY start_date", (agent_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_task(r) for r in rows]

    async def task_update(self, task_id: str, **fields: Any) -> None:
        sets, vals = [], []
        for k, v in fields.items():
            if k == "finish_date" and isinstance(v, datetime):
                v = _ts(v)
            elif hasattr(v, "value"):
                v = v.value
            elif isinstance(v, bool):
                v = int(v)
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(task_id)
        await self._conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = ?", vals)
        await self._conn.commit()

    async def task_delete(self, task_id: str) -> None:
        await self._conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        await self._conn.commit()

    # -----------------------------------------------------------------------
    # Console CRUD
    # -----------------------------------------------------------------------

    async def console_insert(self, agent_id: str, packet: bytes) -> None:
        await self._conn.execute(
            "INSERT INTO consoles (agent_id, packet) VALUES (?, ?)", (agent_id, packet)
        )
        await self._conn.commit()

    async def console_list(self, agent_id: str) -> list[bytes]:
        async with self._conn.execute(
            "SELECT packet FROM consoles WHERE agent_id = ? ORDER BY id", (agent_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [bytes(r["packet"]) for r in rows]

    async def console_clear(self, agent_id: str) -> None:
        await self._conn.execute("DELETE FROM consoles WHERE agent_id = ?", (agent_id,))
        await self._conn.commit()

    # -----------------------------------------------------------------------
    # Download CRUD
    # -----------------------------------------------------------------------

    async def download_insert(self, data: DownloadData) -> None:
        await self._conn.execute(
            "INSERT INTO downloads (file_id, agent_id, agent_name, user, computer,"
            " remote_path, local_path, total_size, recv_size, date, state)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                data.file_id,
                data.agent_id,
                data.agent_name,
                data.user,
                data.computer,
                data.remote_path,
                data.local_path,
                data.total_size,
                data.recv_size,
                _ts(data.date),
                int(data.state),
            ),
        )
        await self._conn.commit()

    def _row_to_download(self, row: aiosqlite.Row) -> DownloadData:
        return DownloadData(
            file_id=row["file_id"],
            agent_id=row["agent_id"],
            agent_name=row["agent_name"],
            user=row["user"],
            computer=row["computer"],
            remote_path=row["remote_path"],
            local_path=row["local_path"],
            total_size=row["total_size"],
            recv_size=row["recv_size"],
            date=_dt(row["date"]),
            state=DownloadState(row["state"]),
        )

    async def download_get(self, file_id: str) -> DownloadData | None:
        async with self._conn.execute(
            "SELECT * FROM downloads WHERE file_id = ?", (file_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_download(row) if row else None

    async def download_list(self) -> list[DownloadData]:
        async with self._conn.execute("SELECT * FROM downloads ORDER BY date") as cur:
            rows = await cur.fetchall()
        return [self._row_to_download(r) for r in rows]

    async def download_update(self, file_id: str, **fields: Any) -> None:
        sets, vals = [], []
        for k, v in fields.items():
            if hasattr(v, "value"):
                v = v.value
            elif isinstance(v, bool):
                v = int(v)
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(file_id)
        await self._conn.execute(f"UPDATE downloads SET {', '.join(sets)} WHERE file_id = ?", vals)
        await self._conn.commit()

    async def download_delete(self, file_id: str) -> None:
        await self._conn.execute("DELETE FROM downloads WHERE file_id = ?", (file_id,))
        await self._conn.commit()

    # -----------------------------------------------------------------------
    # Credential CRUD
    # -----------------------------------------------------------------------

    async def credential_insert(self, data: CredentialData) -> None:
        await self._conn.execute(
            "INSERT INTO credentials (cred_id, username, secret, realm, cred_type,"
            " tag, date, source, agent_id, host)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                data.cred_id,
                data.username,
                self._encrypt_credential_secret(data.secret),
                data.realm,
                data.cred_type.value,
                data.tag,
                _ts(data.date),
                data.source,
                data.agent_id,
                data.host,
            ),
        )
        await self._conn.commit()

    def _row_to_credential(self, row: aiosqlite.Row) -> CredentialData:
        data = CredentialData(
            cred_id=row["cred_id"],
            username=row["username"],
            secret=self._decrypt_credential_secret(bytes(row["secret"])),
            realm=row["realm"],
            cred_type=CredentialType(row["cred_type"]),
            tag=row["tag"],
            date=_dt(row["date"]),
            source=row["source"],
            agent_id=row["agent_id"],
            host=row["host"],
        )
        return data

    async def credential_get(self, cred_id: str) -> CredentialData | None:
        async with self._conn.execute(
            "SELECT * FROM credentials WHERE cred_id = ?", (cred_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_credential(row) if row else None

    async def credential_list(self) -> list[CredentialData]:
        async with self._conn.execute("SELECT * FROM credentials ORDER BY date") as cur:
            rows = await cur.fetchall()
        return [self._row_to_credential(r) for r in rows]

    async def credential_update(self, cred_id: str, **fields: Any) -> None:
        sets, vals = [], []
        for k, v in fields.items():
            if hasattr(v, "value"):
                v = v.value
            if k == "secret":
                v = self._encrypt_credential_secret(str(v))
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(cred_id)
        await self._conn.execute(
            f"UPDATE credentials SET {', '.join(sets)} WHERE cred_id = ?", vals
        )
        await self._conn.commit()

    async def credential_delete(self, cred_id: str) -> None:
        await self._conn.execute("DELETE FROM credentials WHERE cred_id = ?", (cred_id,))
        await self._conn.commit()

    # -----------------------------------------------------------------------
    # Target CRUD
    # -----------------------------------------------------------------------

    async def target_insert(self, data: TargetData) -> None:
        await self._conn.execute(
            "INSERT INTO targets (target_id, computer, domain, address, os, os_desc,"
            " tag, info, date, alive, agents)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                data.target_id,
                data.computer,
                data.domain,
                data.address,
                data.os,
                data.os_desc,
                data.tag,
                data.info,
                _ts(data.date),
                int(data.alive),
                json.dumps(data.agents),
            ),
        )
        await self._conn.commit()

    def _row_to_target(self, row: aiosqlite.Row) -> TargetData:
        return TargetData(
            target_id=row["target_id"],
            computer=row["computer"],
            domain=row["domain"],
            address=row["address"],
            os=row["os"],
            os_desc=row["os_desc"],
            tag=row["tag"],
            info=row["info"],
            date=_dt(row["date"]),
            alive=bool(row["alive"]),
            agents=json.loads(row["agents"]),
        )

    async def target_get(self, target_id: str) -> TargetData | None:
        async with self._conn.execute(
            "SELECT * FROM targets WHERE target_id = ?", (target_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_target(row) if row else None

    async def target_list(self) -> list[TargetData]:
        async with self._conn.execute("SELECT * FROM targets ORDER BY date") as cur:
            rows = await cur.fetchall()
        return [self._row_to_target(r) for r in rows]

    async def target_update(self, target_id: str, **fields: Any) -> None:
        sets, vals = [], []
        for k, v in fields.items():
            if k == "agents" and isinstance(v, list):
                v = json.dumps(v)
            elif isinstance(v, bool):
                v = int(v)
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(target_id)
        await self._conn.execute(f"UPDATE targets SET {', '.join(sets)} WHERE target_id = ?", vals)
        await self._conn.commit()

    async def target_delete(self, target_id: str) -> None:
        await self._conn.execute("DELETE FROM targets WHERE target_id = ?", (target_id,))
        await self._conn.commit()

    # -----------------------------------------------------------------------
    # Tunnel CRUD
    # -----------------------------------------------------------------------

    async def tunnel_insert(self, data: TunnelData) -> None:
        await self._conn.execute(
            "INSERT INTO tunnels (tunnel_id, agent_id, tunnel_type, info, lhost, lport,"
            " thost, tport, use_auth, username, password, create_time)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data.tunnel_id,
                data.agent_id,
                str(data.tunnel_type),
                data.info,
                data.lhost,
                data.lport,
                data.thost,
                data.tport,
                int(data.use_auth),
                data.username,
                data.password,
                _ts(data.create_time),
            ),
        )
        await self._conn.commit()

    def _row_to_tunnel(self, row: aiosqlite.Row) -> TunnelData:
        return TunnelData(
            tunnel_id=row["tunnel_id"],
            agent_id=row["agent_id"],
            tunnel_type=TunnelType(row["tunnel_type"]),
            info=row["info"],
            lhost=row["lhost"],
            lport=row["lport"],
            thost=row["thost"],
            tport=row["tport"],
            use_auth=bool(row["use_auth"]),
            username=row["username"],
            password=row["password"],
            create_time=_dt(row["create_time"]),
        )

    async def tunnel_get(self, tunnel_id: str) -> TunnelData | None:
        async with self._conn.execute(
            "SELECT * FROM tunnels WHERE tunnel_id = ?", (tunnel_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_tunnel(row) if row else None

    async def tunnel_list(self) -> list[TunnelData]:
        async with self._conn.execute("SELECT * FROM tunnels ORDER BY create_time") as cur:
            rows = await cur.fetchall()
        return [self._row_to_tunnel(r) for r in rows]

    async def tunnel_update(self, tunnel_id: str, **fields: Any) -> None:
        _col_map = {"info": "info", "username": "username", "password": "password"}
        sets, vals = [], []
        for k, v in fields.items():
            col = _col_map.get(k, k)
            sets.append(f"{col} = ?")
            vals.append(v)
        vals.append(tunnel_id)
        await self._conn.execute(f"UPDATE tunnels SET {', '.join(sets)} WHERE tunnel_id = ?", vals)
        await self._conn.commit()

    async def tunnel_delete(self, tunnel_id: str) -> None:
        await self._conn.execute("DELETE FROM tunnels WHERE tunnel_id = ?", (tunnel_id,))
        await self._conn.commit()

    # -----------------------------------------------------------------------
    # Chat CRUD
    # -----------------------------------------------------------------------

    async def chat_insert(self, msg: ChatMessage) -> int:
        async with self._conn.execute(
            "INSERT INTO chat (username, message, date) VALUES (?, ?, ?)",
            (msg.username, msg.message, _ts(msg.date)),
        ) as cur:
            rowid = cur.lastrowid
        await self._conn.commit()
        return rowid

    async def chat_list(self, limit: int = 200) -> list[ChatMessage]:
        async with self._conn.execute(
            "SELECT * FROM chat ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [
            ChatMessage(
                id=r["id"],
                username=r["username"],
                message=r["message"],
                date=_dt(r["date"]),
            )
            for r in reversed(rows)
        ]

    # -----------------------------------------------------------------------
    # Utility
    # -----------------------------------------------------------------------

    async def get_journal_mode(self) -> str:
        async with self._conn.execute("PRAGMA journal_mode") as cur:
            row = await cur.fetchone()
        return row[0] if row else ""

    async def table_names(self) -> list[str]:
        async with self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()
        return [r["name"] for r in rows]
