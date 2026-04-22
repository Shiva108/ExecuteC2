# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

ExecuteC2 is a Python-based C2 (Command & Control) teamserver for authorized red team operations. Built on FastAPI + asyncio with SQLite persistence, a WebSocket real-time sync protocol, and AES-256-GCM encrypted agent communications.

**For authorized penetration testing and red team engagements only.**

## Commands

```bash
# Install
make install           # uv pip install -e ".[dev]"

# Run
make run               # python -m executec2 --config config.yaml
make cert              # Generate self-signed TLS cert (dev only)

# Test
make test              # All tests
make test-unit         # tests/unit/ only
make test-int          # tests/integration/ only
make cov               # With coverage report (70% minimum required)

# Single test
uv run pytest tests/unit/test_auth.py::test_login

# Lint / Format
make lint              # ruff check .
make fmt               # ruff format .
```

**CLI:** `executec2 --config config.yaml [--debug] [--host HOST] [--port PORT]`

## Architecture

### Component Map

```text
Operators (HTTPS + WSS)
    ↓
FastAPI App (server/app.py)
    ├── Auth (server/auth.py)          — JWT, OTP, rate limiting
    ├── Database (server/database.py)  — aiosqlite WAL, all CRUD
    ├── MessageBroker (server/broker.py) — async fan-out to all WS clients
    ├── EventManager (server/events.py) — pre/post hooks with timeouts
    ├── TeamserverCore (server/teamserver.py) — agent lifecycle + task dispatch
    └── Routes (server/routes/)         — REST endpoints + /ws/sync
         ↓
Plugins (loaded via importlib)
    ├── HTTPListener (listeners/http_listener.py)
    └── PythonAgentPlugin (agents/python_agent.py)
         ↓
Agents (agent/) — standalone Python payload polling loop
```

### Key Data Flows

**Agent check-in:**
Agent HTTP POST → HTTPListener (decrypt beat header + task responses) → `TeamserverCore.agent_checkin()` → dequeue tasks → encrypt + embed in HTML response → Agent executes, repeats.

**Operator command:**
POST `/api/agents/{id}/commands` → `TeamserverCore.execute_command()` → `plugin.build_task()` → `task_insert()` + enqueue → `MessageBroker.broadcast()` → all WS clients notified → agent picks up on next check-in.

**WebSocket sync:**
POST `/api/auth/otp?type=connect` → GET `/api/sync/ws?otp=<otp>` → binary msgpack frames (Event=append-only, State=last-write-wins per key).

### Encryption Architecture

- **Agent ↔ Listener:** AES-256-GCM, 12-byte random nonce per message
- **Key derivation:** HKDF-SHA256 from per-listener master key → beat key and per-agent session keys
- **Wire format:** `[12-byte nonce][ciphertext][16-byte GCM tag]`; Base64-encoded in beat header
- **Credential storage:** Encrypted at rest with server-derived key

### Plugin System

- **Listeners** extend `ListenerPlugin` ABC (`listeners/base.py`) — implement `start/stop/pause/resume/validate_config/get_info`
- **Agents** extend `AgentPlugin` ABC (`agents/base.py`) — implement `get_info/parse_beat/build_task/process_response/get_commands`
- Loaded at startup via `importlib` from module paths listed in config `plugins:` section

### Agent Lifecycle States

`ACTIVE → INACTIVE → DISCONNECT → TERMINATED → [removed]`

Transitions triggered by `last_tick` age relative to agent sleep interval. State checked by tick updater loop (0.8 sec).

### MessageBroker Backpressure

Per-client send queue max 4096; warn at 75%, drop messages at 95%, disconnect client at 100%. Batch up to 500 packets per `SYNC_CATEGORY_BATCH` frame.

## Configuration

YAML config file with three priority levels (lowest to highest): config file → env vars (`EC2_*`) → CLI flags.

```yaml
server:
  host: "0.0.0.0"
  port: 4321
  data_dir: "./data"
  tls_cert: "./cert.pem"
  tls_key: "./key.pem"
operators:
  username: "plaintext_password" # SHA-256 hashed on load
plugins:
  listeners: ["executec2.listeners.http_listener"]
  agents: ["executec2.agents.python_agent"]
logging:
  level: "INFO"
  format: "json"
```

## Code Conventions

- **Fully async throughout** — no blocking I/O in the event loop; CPU-bound ops use `asyncio.to_thread()`
- **Line length:** 100 chars; **Target:** Python 3.12; **Linter:** ruff (E, F, I, UP rules)
- **ID generation:** Agent IDs = `secrets.token_hex(4)` (8 hex chars); Task IDs = `secrets.token_urlsafe(6)[:8]`; others = UUID4 hex
- **Models:** Pydantic v2 for all data validation; dataclasses for internal structs
- **Logging:** structlog with JSON format; always include `agent_id`, `operator`, `command_name` fields
