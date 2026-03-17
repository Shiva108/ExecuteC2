---
version: 1.0.0
date: 2026-03-17
project: ExecuteC2
language: Python 3.12+
---

# ExecuteC2 — Data Models

## Pydantic Models

All models live in `src/executec2/server/models.py`. Wire serialization uses msgpack for agent communication and JSON for REST API responses.

### AgentData

```python
from pydantic import BaseModel, Field
from enum import IntEnum, StrEnum
from datetime import datetime


class OSType(IntEnum):
    WINDOWS = 1
    LINUX = 2
    MACOS = 3


class AgentMark(StrEnum):
    ACTIVE = ""
    INACTIVE = "inactive"
    DISCONNECT = "disconnect"
    TERMINATED = "terminated"


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
    create_time: datetime = Field(default_factory=datetime.utcnow)
    last_tick: datetime = Field(default_factory=datetime.utcnow)
    kill_date: str = Field(default="", description="ISO 8601 kill date or empty")
    tags: str = Field(default="")
    mark: AgentMark = Field(default=AgentMark.ACTIVE)
    color: str = Field(default="", description="Hex color code for UI")
    target_id: str = Field(default="")
    custom_data: bytes = Field(default=b"")
```

### TaskData

```python
class TaskType(IntEnum):
    TASK = 0
    JOB = 2
    TUNNEL = 3


class MessageType(IntEnum):
    INFO = 0
    SUCCESS = 1
    ERROR = 2
    WARNING = 3


class TaskData(BaseModel):
    task_id: str = Field(description="8-char alphanumeric UID")
    agent_id: str
    task_type: TaskType = Field(default=TaskType.TASK)
    client: str = Field(default="", description="Operator username who issued the task")
    start_date: datetime = Field(default_factory=datetime.utcnow)
    finish_date: datetime | None = Field(default=None)
    command_line: str = Field(default="", description="Human-readable command string")
    message_type: MessageType = Field(default=MessageType.INFO)
    message: str = Field(default="", description="Formatted output for display")
    clear_text: str = Field(default="", description="Plaintext output for search/export")
    completed: bool = Field(default=False)
    data: bytes = Field(default=b"", description="Serialized task payload for agent")
```

### ListenerData

```python
class ListenerStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class ListenerData(BaseModel):
    listener_name: str = Field(description="Unique listener instance name")
    listener_type: str = Field(description="Plugin type name (e.g. 'http')")
    config: dict = Field(description="Listener-specific configuration JSON")
    status: ListenerStatus = Field(default=ListenerStatus.STOPPED)
    create_time: datetime = Field(default_factory=datetime.utcnow)
    watermark: str = Field(default="", description="8-char hex watermark linking to agent type")
```

### CredentialData

```python
class CredentialType(StrEnum):
    PASSWORD = "password"
    HASH_NTLM = "hash_ntlm"
    HASH_SHA256 = "hash_sha256"
    TICKET = "ticket"
    KEY = "key"
    TOKEN = "token"
    OTHER = "other"


class CredentialData(BaseModel):
    cred_id: str = Field(description="Unique credential ID (UUID4 hex)")
    username: str = Field(default="")
    secret: str = Field(default="", description="Password, hash, or token (encrypted at rest)")
    realm: str = Field(default="", description="Domain or realm")
    cred_type: CredentialType = Field(default=CredentialType.PASSWORD)
    tag: str = Field(default="")
    date: datetime = Field(default_factory=datetime.utcnow)
    source: str = Field(default="", description="How this cred was obtained (manual, mimikatz, etc.)")
    agent_id: str = Field(default="", description="Agent that collected this credential")
    host: str = Field(default="", description="Host where credential was found")
```

### TargetData

```python
class TargetData(BaseModel):
    target_id: str = Field(description="Unique target ID (UUID4 hex)")
    computer: str = Field(default="")
    domain: str = Field(default="")
    address: str = Field(default="", description="IP address")
    os: str = Field(default="")
    os_desc: str = Field(default="")
    tag: str = Field(default="")
    info: str = Field(default="", description="Freeform notes")
    date: datetime = Field(default_factory=datetime.utcnow)
    alive: bool = Field(default=True)
    agents: list[str] = Field(default_factory=list, description="Agent IDs on this target")
```

### TunnelData

```python
class TunnelType(StrEnum):
    SOCKS5 = "socks5"
    LOCAL_PORTFWD = "lportfwd"


class TunnelData(BaseModel):
    tunnel_id: str = Field(description="Unique tunnel ID (UUID4 hex)")
    agent_id: str
    tunnel_type: TunnelType
    info: str = Field(default="")
    lhost: str = Field(default="127.0.0.1")
    lport: int
    thost: str = Field(default="", description="Target host (portfwd only)")
    tport: int = Field(default=0, description="Target port (portfwd only)")
    use_auth: bool = Field(default=False, description="SOCKS5 auth (socks5 only)")
    username: str = Field(default="")
    password: str = Field(default="")
    create_time: datetime = Field(default_factory=datetime.utcnow)
```

### DownloadData

```python
class DownloadState(IntEnum):
    IN_PROGRESS = 0
    COMPLETE = 1
    CANCELLED = 2
    ERROR = 3


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
    date: datetime = Field(default_factory=datetime.utcnow)
    state: DownloadState = Field(default=DownloadState.IN_PROGRESS)
```

### ChatMessage

```python
class ChatMessage(BaseModel):
    id: int = Field(default=0)
    username: str
    message: str
    date: datetime = Field(default_factory=datetime.utcnow)
```

### OperatorData

```python
class OperatorData(BaseModel):
    username: str
    password_hash: str = Field(description="SHA-256 hex digest")
```

### OTPEntry

```python
class OTPType(StrEnum):
    CONNECT = "connect"
    TUNNEL = "tunnel"


class OTPEntry(BaseModel):
    otp: str = Field(description="One-time password string")
    otp_type: OTPType
    username: str
    created: datetime = Field(default_factory=datetime.utcnow)
```

### JWT Claims

```python
class TokenClaims(BaseModel):
    username: str
    exp: datetime
    iat: datetime
    token_type: str = Field(description="'access' or 'refresh'")
```

## WebSocket Sync Packet Types

All WebSocket frames are binary: `[1 byte: packet_type] [N bytes: msgpack payload]`.

```python
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
```

## Broker Message

```python
class BrokerMsgType(IntEnum):
    EVENT = 0   # Append-only, ordered delivery
    STATE = 1   # Last-write-wins per state_key


class BrokerMessage(BaseModel):
    msg_type: BrokerMsgType = Field(default=BrokerMsgType.EVENT)
    state_key: str = Field(default="")
    packet_type: SyncPacketType
    data: bytes
    category: str
```

## Client Handler

```python
from asyncio import Queue
from fastapi import WebSocket


class ClientHandler:
    """Represents a connected operator WebSocket session."""

    def __init__(self, ws: WebSocket, username: str):
        self.ws: WebSocket = ws
        self.username: str = username
        self.send_queue: Queue[bytes] = Queue(maxsize=4096)
        self.sync_queue: Queue[bytes] = Queue(maxsize=8192)
        self.subscriptions: set[str] = set()
        self.synced: bool = False
        self.state_store: dict[str, BrokerMessage] = {}
```

## Agent Runtime (server-side)

```python
from asyncio import Queue


class Agent:
    """Server-side representation of a connected agent."""

    def __init__(self, data: AgentData):
        self.data: AgentData = data
        self.pending_tasks: Queue[bytes] = Queue(maxsize=256)
        self.pending_tunnel_tasks: Queue[bytes] = Queue(maxsize=4096)
        self.pending_tunnel_data: Queue[bytes] = Queue(maxsize=4096)
        self.running_tasks: dict[str, TaskData] = {}
        self.running_jobs: dict[str, TaskData] = {}
        self.tick: bool = False
        self.active: bool = True
```

## SQLite Schema

Database file: `<data_dir>/executec2.db`. Pragmas: `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=10000`, `cache_size=-64000`.

### listeners

```sql
CREATE TABLE IF NOT EXISTS listeners (
    listener_name TEXT PRIMARY KEY,
    listener_type TEXT NOT NULL,
    config        TEXT NOT NULL,         -- JSON
    status        TEXT NOT NULL DEFAULT 'stopped',
    create_time   INTEGER NOT NULL,      -- Unix timestamp
    watermark     TEXT NOT NULL DEFAULT ''
);
```

### agents

```sql
CREATE TABLE IF NOT EXISTS agents (
    id           TEXT PRIMARY KEY,       -- 8-char hex
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
    os           INTEGER NOT NULL DEFAULT 2,  -- 1=Win 2=Linux 3=Mac
    os_desc      TEXT NOT NULL DEFAULT '',
    domain       TEXT NOT NULL DEFAULT '',
    computer     TEXT NOT NULL DEFAULT '',
    username     TEXT NOT NULL DEFAULT '',
    create_time  INTEGER NOT NULL,       -- Unix timestamp
    last_tick    INTEGER NOT NULL,       -- Unix timestamp
    kill_date    TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '',
    mark         TEXT NOT NULL DEFAULT '',  -- '' | 'inactive' | 'disconnect' | 'terminated'
    color        TEXT NOT NULL DEFAULT '',
    target_id    TEXT NOT NULL DEFAULT '',
    custom_data  BLOB NOT NULL DEFAULT x''
);
```

### tasks

```sql
CREATE TABLE IF NOT EXISTS tasks (
    task_id      TEXT PRIMARY KEY,       -- 8-char alphanumeric UID
    agent_id     TEXT NOT NULL,
    task_type    INTEGER NOT NULL DEFAULT 0,  -- 0=task 2=job 3=tunnel
    client       TEXT NOT NULL DEFAULT '',
    start_date   INTEGER NOT NULL,       -- Unix timestamp
    finish_date  INTEGER,                -- Unix timestamp or NULL
    command_line TEXT NOT NULL DEFAULT '',
    message_type INTEGER NOT NULL DEFAULT 0,
    message      TEXT NOT NULL DEFAULT '',
    clear_text   TEXT NOT NULL DEFAULT '',
    completed    BOOLEAN NOT NULL DEFAULT 0,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
```

### consoles

```sql
CREATE TABLE IF NOT EXISTS consoles (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    packet   BLOB NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
```

### downloads

```sql
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
```

### credentials

```sql
CREATE TABLE IF NOT EXISTS credentials (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    cred_id   TEXT NOT NULL UNIQUE,
    username  TEXT NOT NULL DEFAULT '',
    secret    BLOB NOT NULL DEFAULT x'',  -- AES-GCM encrypted
    realm     TEXT NOT NULL DEFAULT '',
    cred_type TEXT NOT NULL DEFAULT 'password',
    tag       TEXT NOT NULL DEFAULT '',
    date      INTEGER NOT NULL,
    source    TEXT NOT NULL DEFAULT '',
    agent_id  TEXT NOT NULL DEFAULT '',
    host      TEXT NOT NULL DEFAULT ''
);
```

### targets

```sql
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
    agents    TEXT NOT NULL DEFAULT '[]'  -- JSON array of agent IDs
);
```

### chat

```sql
CREATE TABLE IF NOT EXISTS chat (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    message  TEXT NOT NULL,
    date     INTEGER NOT NULL
);
```

## Serialization Formats

### REST API (Operator ↔ Teamserver)

- **Content-Type:** `application/json`
- **Models:** Pydantic `.model_dump(mode="json")` for serialization, `.model_validate()` for deserialization
- **Dates:** ISO 8601 strings in JSON responses

### WebSocket Sync (Teamserver → Operator)

- **Format:** Binary frames: `[1 byte packet_type][msgpack payload]`
- **Encoding:** msgpack for compact binary serialization
- **Batch:** `SYNC_CATEGORY_BATCH` wraps up to 500 individual packets

### Agent Wire Protocol (Agent ↔ Listener)

- **Format:** AES-256-GCM encrypted msgpack
- **Structure:** `[12-byte nonce][ciphertext][16-byte GCM tag]`
- **Inner payload:** msgpack-encoded dict with command ID and args

See [04_PROTOCOL_SPEC.md](04_PROTOCOL_SPEC.md) for full wire format specification.

## ID Generation

| Entity | Format | Generator |
|---|---|---|
| Agent ID | 8-char hex | `secrets.token_hex(4)` |
| Task ID | 8-char alphanumeric | `secrets.token_urlsafe(6)[:8]` |
| Credential ID | UUID4 hex | `uuid.uuid4().hex` |
| Target ID | UUID4 hex | `uuid.uuid4().hex` |
| Tunnel ID | UUID4 hex | `uuid.uuid4().hex` |
| Download File ID | UUID4 hex | `uuid.uuid4().hex` |
| OTP | 32-char hex | `secrets.token_hex(16)` |
