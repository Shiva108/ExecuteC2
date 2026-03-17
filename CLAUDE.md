# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Pre-implementation: specification documents exist, no source code yet. The next action is generating SSD documents in `docs/ssd/` using the spec-driven design prompt in `.claude/create-sdd-implementation.md`.

## What This Project Is

**ExecuteC2** is a Python-based C2 (command and control) teamserver for authorized red team operations, built on a Python/FastAPI/asyncio stack.

| Aspect | ExecuteC2 target |
| --- | --- |
| Teamserver | Python (asyncio) + FastAPI |
| Database | SQLite (WAL) via aiosqlite |
| Auth | JWT (HMAC-SHA256) |
| WebSocket | FastAPI WebSocket / websockets |
| Plugin system | Python modules via importlib |
| Agents | Python agent (cross-platform) |
| Transport encryption | AES-GCM / ChaCha20-Poly1305 |
| Client interface | Web UI + REST API + CLI |

## Architecture Overview

Component model:

```text
Agent → Listener Plugin → Teamserver (FastAPI) → SQLite + MessageBroker → WebSocket → Operator Clients
```

Key components to build (from `.claude/create-sdd-implementation.md`):

- **FastAPI app** — HTTPS REST API + WebSocket sync
- **MessageBroker** — asyncio fan-out broadcast to connected operator clients
- **aiosqlite DBMS** — Persistent storage for agents, tasks, credentials, targets
- **Plugin loader** — Python ABC classes loaded via importlib
- **Agent lifecycle** — State machine: Active → Inactive → Disconnect → Terminated
- **Task/Job routing** — Async task queue with type dispatch (task, job, tunnel, proxy)
- **TunnelManager** — SOCKS4/5 + local/reverse port-forwarding via asyncio streams

## SSD Documents

When created, ExecuteC2's own design specs will live in `docs/ssd/` (Tier 1 → Tier 2 → Tier 3 order):

1. `01_ARCHITECTURE.md` → `02_DATA_MODELS.md` → `03_API_REFERENCE.md`
2. `04_PROTOCOL_SPEC.md` → `05_AGENT_SPEC.md` → `06_CONFIG_SPEC.md`
3. `07_IMPLEMENTATION_PLAN.md` → `08_TEST_SPEC.md` → `09_DEPLOYMENT_SPEC.md`

Every SSD file must include the frontmatter block:

```yaml
---
version: 1.0.0
date: 2026-03-16
project: ExecuteC2
---
```

## Implementation Phases (planned)

From `.claude/create-sdd-implementation.md`, the 13 build phases in dependency order:

1. Project Skeleton (pyproject.toml, directory layout, CLI entry)
2. Database Layer (aiosqlite, schema, CRUD for all models)
3. Auth & HTTP API (FastAPI, JWT login/refresh)
4. WebSocket Sync (connection manager, message broker, subscriptions)
5. Listener Framework (plugin loader, listener ABC, HTTP/S listener)
6. Agent Framework (agent model, lifecycle state machine, task queue)
7. Command System (dispatch, registry, built-in commands)
8. Agent Transport (Python agent payload, HTTP connector, encryption, check-in loop)
9. Task & Job Management (task types, job lifecycle, routing)
10. Tunneling (SOCKS4/5, local/remote port forwarding)
11. Credential & Target Management (CRUD + event broadcast)
12. Agent Builder (cross-platform agent compilation/packaging)
13. Web UI (operator dashboard — deferrable)

## Commands

_No build system yet — update this section when pyproject.toml is created._

```bash
# Placeholder — fill in when source code exists
uv run python -m executec2          # run server
uv run pytest tests/                # run all tests
uv run pytest tests/test_foo.py::test_bar  # run single test
uv run ruff check .                 # lint
uv run ruff format .                # format
```
