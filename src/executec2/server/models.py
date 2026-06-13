"""All Pydantic models, enums, and runtime container classes for ExecuteC2."""

import asyncio
from datetime import UTC, datetime
from enum import IntEnum, StrEnum

from fastapi import WebSocket
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OSType(IntEnum):
    WINDOWS = 1
    LINUX = 2
    MACOS = 3


class AgentMark(StrEnum):
    ACTIVE = ""
    INACTIVE = "inactive"
    DISCONNECT = "disconnect"
    TERMINATED = "terminated"


class TaskType(IntEnum):
    TASK = 0
    JOB = 2
    TUNNEL = 3


class MessageType(IntEnum):
    INFO = 0
    SUCCESS = 1
    ERROR = 2
    WARNING = 3


class ListenerStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class InfraStage(IntEnum):
    STAGE_0 = 0
    STAGE_1 = 1
    STAGE_2 = 2
    STAGE_3 = 3


class InfrastructureAssetType(StrEnum):
    TEAMSERVER = "teamserver"
    LISTENER = "listener"
    CDN_EDGE = "cdn_edge"
    REDIRECTOR = "redirector"
    DOMAIN = "domain"
    CERTIFICATE = "certificate"


class DeployTarget(StrEnum):
    DOCKER_COMPOSE = "docker_compose"
    TERRAFORM = "terraform"


class DeploymentRunStatus(StrEnum):
    DRAFT = "draft"
    PLANNED = "planned"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"
    DRIFTED = "drifted"
    TEARING_DOWN = "tearing_down"
    TORN_DOWN = "torn_down"
    ROTATING = "rotating"


class InfraHealthStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"


class TrafficProfileTLSMode(StrEnum):
    DISABLED = "disabled"
    OPTIONAL = "optional"
    REQUIRED = "required"


class TrafficProfileKind(StrEnum):
    EXPLICIT = "explicit"
    IMPLICIT = "implicit"


class CredentialType(StrEnum):
    PASSWORD = "password"
    HASH_NTLM = "hash_ntlm"
    HASH_SHA256 = "hash_sha256"
    TICKET = "ticket"
    KEY = "key"
    TOKEN = "token"
    OTHER = "other"


class TunnelType(StrEnum):
    SOCKS5 = "socks5"
    LOCAL_PORTFWD = "lportfwd"


class SessionType(StrEnum):
    SHELL = "shell"
    PORTFWD = "portfwd"
    SOCKS = "socks"


class SessionStatus(StrEnum):
    OPENING = "opening"
    ACTIVE = "active"
    CLOSED = "closed"
    ERROR = "error"
    TERMINATED = "terminated"


class DownloadState(IntEnum):
    IN_PROGRESS = 0
    COMPLETE = 1
    CANCELLED = 2
    ERROR = 3


class OTPType(StrEnum):
    CONNECT = "connect"
    TUNNEL = "tunnel"
    SESSION = "session"


class SyncPacketType(IntEnum):
    # Sync control
    SYNC_START = 0x11
    SYNC_FINISH = 0x12
    SYNC_BATCH = 0x14
    SYNC_CATEGORY_BATCH = 0x15

    # Chat
    CHAT_MESSAGE = 0x18

    # Listeners
    LISTENER_START = 0x31
    LISTENER_EDIT = 0x32
    LISTENER_STOP = 0x33

    # Agents
    AGENT_NEW = 0x41
    AGENT_UPDATE = 0x42
    AGENT_REMOVE = 0x43
    AGENT_TICK = 0x44

    # Tasks
    AGENT_TASK_SYNC = 0x49
    AGENT_TASK_UPDATE = 0x4A
    AGENT_TASK_SEND = 0x4B
    AGENT_TASK_REMOVE = 0x4C

    # Downloads
    DOWNLOAD_CREATE = 0x51
    DOWNLOAD_UPDATE = 0x52
    DOWNLOAD_DELETE = 0x53
    DOWNLOAD_COMPLETE = 0x54

    # Tunnels
    TUNNEL_CREATE = 0x57
    TUNNEL_UPDATE = 0x58
    TUNNEL_DELETE = 0x59

    # Sessions
    SESSION_CREATE = 0x5D
    SESSION_UPDATE = 0x5E
    SESSION_DELETE = 0x5F

    # Console
    AGENT_CONSOLE_OUTPUT = 0x69
    AGENT_CONSOLE_CLEAR = 0x6A

    # Credentials
    CREDS_CREATE = 0x81
    CREDS_UPDATE = 0x82
    CREDS_DELETE = 0x83

    # Targets
    TARGETS_CREATE = 0x87
    TARGETS_UPDATE = 0x88
    TARGETS_DELETE = 0x89

    # Infrastructure
    INFRA_ASSET_CREATE = 0x91
    INFRA_ASSET_UPDATE = 0x92
    INFRA_ASSET_DELETE = 0x93
    TRAFFIC_PROFILE_CREATE = 0x94
    TRAFFIC_PROFILE_UPDATE = 0x95
    TRAFFIC_PROFILE_DELETE = 0x96
    DEPLOYMENT_RUN_CREATE = 0x97
    DEPLOYMENT_RUN_UPDATE = 0x98
    DEPLOYMENT_RUN_DELETE = 0x99


class BrokerMsgType(IntEnum):
    EVENT = 0  # Append-only, ordered delivery
    STATE = 1  # Last-write-wins per state_key


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class AgentData(BaseModel):
    id: str = Field(description="Unique agent ID (8-char hex)")
    name: str = Field(description="Agent type name (e.g. 'python')")
    session_key: bytes = Field(description="Per-agent derived encryption key")
    listener: str = Field(description="Listener name this agent connected through")
    external_ip: str = Field(default="")
    internal_ip: str = Field(default="")
    gmt_offset: int = Field(default=0)
    sleep: int = Field(description="Sleep interval in seconds")
    jitter: int = Field(default=0, description="Jitter percentage (0-100)")
    pid: int = Field(default=0)
    tid: int = Field(default=0)
    arch: str = Field(default="", description="x86 | x64 | arm64")
    elevated: bool = Field(default=False)
    process: str = Field(default="", description="Process name hosting the agent")
    os: OSType = Field(description="Operating system type")
    os_desc: str = Field(default="", description="OS version string")
    domain: str = Field(default="")
    computer: str = Field(default="")
    username: str = Field(default="")
    create_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_tick: datetime = Field(default_factory=lambda: datetime.now(UTC))
    kill_date: str = Field(default="", description="ISO 8601 kill date or empty")
    tags: str = Field(default="")
    mark: AgentMark = Field(default=AgentMark.ACTIVE)
    color: str = Field(default="", description="Hex color code for UI")
    target_id: str = Field(default="")
    custom_data: bytes = Field(default=b"")
    last_counter: int = Field(default=0, ge=0)

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("create_time", "last_tick", mode="after")
    @classmethod
    def _ensure_utc(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class TaskData(BaseModel):
    task_id: str = Field(description="8-char alphanumeric UID")
    agent_id: str
    task_type: TaskType = Field(default=TaskType.TASK)
    client: str = Field(default="", description="Operator username who issued the task")
    start_date: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finish_date: datetime | None = Field(default=None)
    command_line: str = Field(default="", description="Human-readable command string")
    message_type: MessageType = Field(default=MessageType.INFO)
    message: str = Field(default="", description="Formatted output for display")
    clear_text: str = Field(default="", description="Plaintext output for search/export")
    completed: bool = Field(default=False)
    data: bytes = Field(default=b"", description="Serialized task payload for agent")


class ListenerData(BaseModel):
    listener_name: str = Field(description="Unique listener instance name")
    listener_type: str = Field(description="Plugin type name (e.g. 'http')")
    config: dict = Field(description="Listener-specific configuration JSON")
    traffic_profile_id: str = Field(default="")
    ingress_asset_id: str = Field(default="")
    status: ListenerStatus = Field(default=ListenerStatus.STOPPED)
    create_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    watermark: str = Field(default="", description="8-char hex watermark linking to agent type")


class TrafficProfileData(BaseModel):
    profile_id: str = Field(description="Unique traffic profile ID")
    name: str
    listener_type: str = Field(default="http")
    stage: InfraStage = Field(default=InfraStage.STAGE_1)
    profile_kind: TrafficProfileKind = Field(default=TrafficProfileKind.EXPLICIT)
    callback_hostnames: list[str] = Field(default_factory=list)
    uris: list[str] = Field(default_factory=list)
    http_method: str = Field(default="POST")
    user_agents: list[str] = Field(default_factory=list)
    host_headers: list[str] = Field(default_factory=list)
    request_headers: dict[str, str] = Field(default_factory=dict)
    response_headers: dict[str, str] = Field(default_factory=dict)
    trust_x_forwarded_for: bool = Field(default=False)
    page_error: str = Field(default="")
    page_payload: str = Field(default="")
    tls_mode: TrafficProfileTLSMode = Field(default=TrafficProfileTLSMode.OPTIONAL)
    source_listener: str = Field(default="")
    create_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    update_time: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("create_time", "update_time", mode="after")
    @classmethod
    def _ensure_profile_utc(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class InfrastructureAssetData(BaseModel):
    asset_id: str = Field(description="Unique infrastructure asset ID")
    name: str
    asset_type: InfrastructureAssetType
    stage: InfraStage
    provider: str = Field(default="")
    parent_asset_id: str = Field(default="")
    linked_listener_name: str = Field(default="")
    traffic_profile_id: str = Field(default="")
    owner: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    deploy_target: DeployTarget = Field(default=DeployTarget.DOCKER_COMPOSE)
    health: InfraHealthStatus = Field(default=InfraHealthStatus.UNKNOWN)
    dns_state: str = Field(default="")
    certificate_expires_at: datetime | None = Field(default=None)
    upstream_asset_ids: list[str] = Field(default_factory=list)
    downstream_asset_ids: list[str] = Field(default_factory=list)
    stage_owner: str = Field(default="")
    rendered_checksum: str = Field(default="")
    last_deployment_run_id: str = Field(default="")
    last_health_observed_at: datetime | None = Field(default=None)
    create_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    update_time: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator(
        "certificate_expires_at",
        "last_health_observed_at",
        "create_time",
        "update_time",
        mode="after",
    )
    @classmethod
    def _ensure_asset_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class DeploymentRunData(BaseModel):
    run_id: str = Field(description="Unique deployment run ID")
    asset_id: str
    operation: str
    target: DeployTarget
    status: DeploymentRunStatus
    created_by: str = Field(default="")
    artifact_dir: str = Field(default="")
    plan_data: dict = Field(default_factory=dict)
    provider_responses: dict = Field(default_factory=dict)
    error: str = Field(default="")
    failure_reason: str = Field(default="")
    failure_phase: str = Field(default="")
    backend_commands: list[dict] = Field(default_factory=list)
    execution_log: list[dict] = Field(default_factory=list)
    health_checks: list[dict] = Field(default_factory=list)
    rollback_data: dict = Field(default_factory=dict)
    replacement_asset_id: str = Field(default="")
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    timeout_seconds: int = Field(default=90)
    create_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    update_time: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("started_at", "finished_at", "create_time", "update_time", mode="after")
    @classmethod
    def _ensure_run_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class InfraHealthSnapshotData(BaseModel):
    snapshot_id: str = Field(description="Unique health snapshot ID")
    asset_id: str
    status: InfraHealthStatus
    summary: str = Field(default="")
    details: dict = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("observed_at", mode="after")
    @classmethod
    def _ensure_snapshot_utc(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class CredentialData(BaseModel):
    cred_id: str = Field(description="Unique credential ID (UUID4 hex)")
    username: str = Field(default="")
    secret: str = Field(default="", description="Password, hash, or token (encrypted at rest)")
    realm: str = Field(default="", description="Domain or realm")
    cred_type: CredentialType = Field(default=CredentialType.PASSWORD)
    tag: str = Field(default="")
    date: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = Field(default="", description="How this cred was obtained")
    agent_id: str = Field(default="", description="Agent that collected this credential")
    host: str = Field(default="", description="Host where credential was found")


class TargetData(BaseModel):
    target_id: str = Field(description="Unique target ID (UUID4 hex)")
    computer: str = Field(default="")
    domain: str = Field(default="")
    address: str = Field(default="", description="IP address")
    os: str = Field(default="")
    os_desc: str = Field(default="")
    tag: str = Field(default="")
    info: str = Field(default="", description="Freeform notes")
    date: datetime = Field(default_factory=lambda: datetime.now(UTC))
    alive: bool = Field(default=True)
    agents: list[str] = Field(default_factory=list, description="Agent IDs on this target")


class TunnelData(BaseModel):
    tunnel_id: str = Field(description="Unique tunnel ID (UUID4 hex)")
    agent_id: str
    tunnel_type: TunnelType
    info: str = Field(default="")
    lhost: str = Field(default="127.0.0.1")
    lport: int
    thost: str = Field(default="", description="Target host (portfwd only)")
    tport: int = Field(default=0, description="Target port (portfwd only)")
    use_auth: bool = Field(default=False, description="SOCKS5 auth")
    username: str = Field(default="")
    password: str = Field(default="")
    create_time: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SessionData(BaseModel):
    session_id: str = Field(description="Unique session ID")
    agent_id: str
    session_type: SessionType
    status: SessionStatus = Field(default=SessionStatus.OPENING)
    created_by: str = Field(default="")
    metadata: dict = Field(default_factory=dict)
    opened_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    closed_at: datetime | None = Field(default=None)
    last_activity_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("opened_at", "closed_at", "last_activity_at", mode="after")
    @classmethod
    def _ensure_session_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class DownloadData(BaseModel):
    file_id: str = Field(description="Unique download ID (UUID4 hex)")
    agent_id: str
    agent_name: str = Field(default="")
    user: str = Field(default="", description="Username on target")
    computer: str = Field(default="")
    remote_path: str = Field(description="Source path on target")
    local_path: str = Field(default="", description="Local save path on teamserver")
    total_size: int = Field(default=0)
    recv_size: int = Field(default=0)
    date: datetime = Field(default_factory=lambda: datetime.now(UTC))
    state: DownloadState = Field(default=DownloadState.IN_PROGRESS)


class ChatMessage(BaseModel):
    id: int = Field(default=0)
    username: str
    message: str
    date: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OperatorData(BaseModel):
    username: str
    password_hash: str = Field(description="SHA-256 hex digest")


class OTPEntry(BaseModel):
    otp: str = Field(description="One-time password string")
    otp_type: OTPType
    username: str
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("created", mode="after")
    @classmethod
    def _ensure_utc(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class TokenClaims(BaseModel):
    sub: str
    username: str
    roles: list[str] = Field(default_factory=list)
    jti: str = Field(default="")
    exp: datetime
    iat: datetime
    token_type: str = Field(description="'access' or 'refresh'")


class BrokerMessage(BaseModel):
    msg_type: BrokerMsgType = Field(default=BrokerMsgType.EVENT)
    state_key: str = Field(default="")
    packet_type: SyncPacketType
    data: bytes
    category: str


# ---------------------------------------------------------------------------
# Runtime containers (not stored in DB, live in memory)
# ---------------------------------------------------------------------------


class ClientHandler:
    """Represents a connected operator WebSocket session."""

    def __init__(self, ws: WebSocket, username: str):
        self.ws: WebSocket = ws
        self.username: str = username
        self.send_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=4096)
        self.sync_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8192)
        self.subscriptions: set[str] = set()
        self.synced: bool = False
        self.state_store: dict[str, BrokerMessage] = {}


class Agent:
    """Server-side representation of a connected agent."""

    def __init__(self, data: AgentData):
        self.data: AgentData = data
        self.pending_tasks: asyncio.Queue[bytes] = asyncio.Queue(maxsize=256)
        self.pending_tunnel_tasks: asyncio.Queue[bytes] = asyncio.Queue(maxsize=4096)
        self.pending_tunnel_data: asyncio.Queue[bytes] = asyncio.Queue(maxsize=4096)
        self.running_tasks: dict[str, TaskData] = {}
        self.running_jobs: dict[str, TaskData] = {}
        self.transport: str = "http"
        self.listener_master_key: bytes | None = None
        self.ws = None
        self.outbound_seq: int = 1
        self.inbound_seq: int = 0
        self.tick: bool = False
        self.active: bool = True
