---
version: 1.0.0
date: 2026-03-17
project: ExecuteC2
language: Python 3.12+
---

# ExecuteC2 — Configuration Spec

## Server Configuration (`config.yaml`)

The teamserver is launched with: `python -m executec2 --config config.yaml [--debug]`

### Full Schema

```yaml
server:
  host: "0.0.0.0"                    # Bind address for the teamserver API
  port: 4321                          # HTTPS + WebSocket port
  data_dir: "./data"                  # Directory for SQLite DB + downloads
  tls_cert: "/path/to/cert.pem"      # TLS certificate (required)
  tls_key: "/path/to/key.pem"        # TLS private key (required)
  access_token_ttl: 24               # Access token lifetime in hours (default: 24)
  refresh_token_ttl: 168             # Refresh token lifetime in hours (default: 168 = 7d)
  auth_rate_limit: 10                # Max auth attempts per IP per minute

operators:
  admin: "password123"               # username: plaintext password (SHA256'd at compare)
  operator1: "pass456"

plugins:
  listeners:
    - "executec2.listeners.http_listener"   # Module paths for listener plugins
  agents:
    - "executec2.agents.python_agent"       # Module paths for agent plugins

logging:
  level: "INFO"                       # DEBUG, INFO, WARNING, ERROR
  format: "json"                      # "json" (structlog) or "console"
  file: ""                            # Log file path (empty = stdout only)
```

### Pydantic Config Schema (`src/executec2/config/schema.py`)

```python
from pydantic import BaseModel, Field, field_validator
from pathlib import Path


class ServerConfig(BaseModel):
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=4321, ge=1, le=65535)
    data_dir: Path = Field(default=Path("./data"))
    tls_cert: Path
    tls_key: Path
    access_token_ttl: int = Field(default=24, ge=1, description="Hours")
    refresh_token_ttl: int = Field(default=168, ge=1, description="Hours")
    auth_rate_limit: int = Field(default=10, ge=1, description="Requests per minute per IP")

    @field_validator("data_dir")
    @classmethod
    def ensure_data_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v


class PluginConfig(BaseModel):
    listeners: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)


class LoggingConfig(BaseModel):
    level: str = Field(default="INFO")
    format: str = Field(default="json")
    file: str = Field(default="")


class ExecuteC2Config(BaseModel):
    server: ServerConfig
    operators: dict[str, str] = Field(description="username -> plaintext password")
    plugins: PluginConfig = Field(default_factory=PluginConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
```

## HTTP Listener Config

Per-listener instance configuration stored in the `listeners` table as JSON. Passed to `HTTPListener.start(config)`.

```python
class HTTPListenerConfig(BaseModel):
    host_bind: str = Field(default="0.0.0.0")
    port_bind: int = Field(ge=1, le=65535)
    callback_addresses: list[str] = Field(
        min_length=1,
        description="URLs agents use to reach this listener (e.g. https://c2.example.com:443)",
    )
    encrypt_key: str = Field(
        min_length=64, max_length=64,
        description="64 hex chars = 32-byte AES-256 key",
    )
    ssl: bool = Field(default=False)
    ssl_cert: str = Field(default="", description="PEM cert path (auto-generates if empty + ssl=True)")
    ssl_key: str = Field(default="", description="PEM key path")
    http_method: str = Field(default="POST", pattern="^(GET|POST)$")
    uris: list[str] = Field(
        min_length=1,
        description="Valid URI paths for agent check-ins",
    )
    beat_header: str = Field(
        description="HTTP header name carrying encrypted beat data",
    )
    user_agents: list[str] = Field(
        default_factory=list,
        description="Allowed User-Agent values (empty = allow all)",
    )
    host_headers: list[str] = Field(
        default_factory=list,
        description="Allowed Host header values (empty = allow all)",
    )
    request_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional headers agents must send",
    )
    response_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Extra response headers",
    )
    trust_x_forwarded_for: bool = Field(default=False)
    page_error: str = Field(
        default="<html><body>404 Not Found</body></html>",
        description="HTML response for non-agent requests",
    )
    page_payload: str = Field(
        description="HTML template containing <<<PAYLOAD_DATA>>> marker",
    )
```

## Agent Build Config

Configuration for generating a Python agent payload. Passed when an operator requests agent generation or configures the agent for deployment.

```python
class AgentBuildConfig(BaseModel):
    listener_name: str = Field(description="Target listener to connect to")
    sleep: int = Field(default=60, ge=1, description="Sleep interval in seconds")
    jitter: int = Field(default=20, ge=0, le=100, description="Jitter percentage")
    kill_date: str = Field(default="", description="ISO 8601 date or empty (no kill date)")
```

The agent payload is generated by injecting the listener's callback addresses, encryption key, and agent build config into the `agent/` package template.

## Runtime Constants

| Constant | Value | Location | Description |
|---|---|---|---|
| Agent tick interval | 800 ms | `server/app.py` | `agent_tick_updater` loop interval |
| Client send_queue capacity | 4096 | `server/broker.py` | Per-client WebSocket outbound buffer |
| Client sync_queue capacity | 8192 | `server/broker.py` | Per-client sync-phase buffer |
| Broker broadcast capacity | 8192 | `server/broker.py` | MessageBroker broadcast queue |
| Agent pending_tasks capacity | 256 | `server/models.py` | Per-agent pending task queue |
| Agent pending_tunnel_tasks capacity | 4096 | `server/models.py` | Per-agent tunnel task queue |
| Agent pending_tunnel_data capacity | 4096 | `server/models.py` | Per-agent tunnel data queue |
| Max task dequeue size | 25 MB | `server/routes/agents.py` | Max bytes dequeued per check-in |
| EventManager workers | 4 | `server/events.py` | Async post-hook worker tasks |
| EventManager queue | 256 | `server/events.py` | Hook job queue capacity |
| Pre-hook timeout | 5 s | `server/events.py` | Synchronous hook execution limit |
| Post-hook timeout | 30 s | `server/events.py` | Async hook execution limit |
| Sync batch size | 500 | `server/broker.py` | Packets per `SYNC_CATEGORY_BATCH` |
| DB busy timeout | 10000 ms | `server/database.py` | SQLite `busy_timeout` pragma |
| DB cache size | 64 MB | `server/database.py` | SQLite `cache_size` pragma (-64000) |
| OTP TTL | 60 s | `server/auth.py` | One-time password expiration |
| Auth rate limit | 10 req/min | `server/auth.py` | Per-IP login rate limit (configurable) |
| Inactive threshold | 3× sleep | `server/app.py` | Agent marked inactive after 3× its sleep interval |
| Backpressure warning | 75% | `server/broker.py` | Log warning at 75% send_queue fill |
| Backpressure drop | 95% | `server/broker.py` | Drop messages at 95% fill |
| Backpressure disconnect | 100% | `server/broker.py` | Close connection at 100% fill |

## Environment Variables

ExecuteC2 supports environment variable overrides for deployment flexibility:

| Variable | Override | Default |
|---|---|---|
| `EC2_CONFIG` | Config file path | `config.yaml` |
| `EC2_HOST` | `server.host` | `0.0.0.0` |
| `EC2_PORT` | `server.port` | `4321` |
| `EC2_DATA_DIR` | `server.data_dir` | `./data` |
| `EC2_TLS_CERT` | `server.tls_cert` | (required) |
| `EC2_TLS_KEY` | `server.tls_key` | (required) |
| `EC2_LOG_LEVEL` | `logging.level` | `INFO` |
| `EC2_DEBUG` | Enable debug mode | `false` |

Environment variables take precedence over `config.yaml` values. Config file values take precedence over defaults.

## CLI Interface (`src/executec2/__main__.py`)

```python
import argparse

def main():
    parser = argparse.ArgumentParser(
        prog="executec2",
        description="ExecuteC2 Teamserver",
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--host",
        help="Override bind address",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        help="Override listen port",
    )
    args = parser.parse_args()
    # Load config, apply overrides, start server
```
