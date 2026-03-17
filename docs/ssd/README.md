---
version: 1.0.0
date: 2026-03-17
project: ExecuteC2
language: Python 3.12+
---

# ExecuteC2 — Spec-Driven Design Documents

Complete specification for the ExecuteC2 teamserver, a Python-based C2 framework for authorized red team operations.

## Tier 1 — Core Architecture

| Document | Description |
|---|---|
| [01_ARCHITECTURE.md](01_ARCHITECTURE.md) | System design, component diagram, data flows, startup sequence, security model |
| [02_DATA_MODELS.md](02_DATA_MODELS.md) | Pydantic models, SQLite schemas, WebSocket packet types, serialization formats |
| [03_API_REFERENCE.md](03_API_REFERENCE.md) | Complete REST API (auth, agents, listeners, tasks, tunnels, credentials, targets) + WebSocket sync protocol |

## Tier 2 — Protocols and Agents

| Document | Description |
|---|---|
| [04_PROTOCOL_SPEC.md](04_PROTOCOL_SPEC.md) | HTTP/S agent wire protocol, AES-GCM encryption, check-in/response format, tunnel data protocol |
| [05_AGENT_SPEC.md](05_AGENT_SPEC.md) | Plugin ABCs, agent lifecycle state machine, command registry, Python agent architecture, event system |
| [06_CONFIG_SPEC.md](06_CONFIG_SPEC.md) | Server config.yaml schema, listener configs, agent build config, runtime constants, environment variables |

## Tier 3 — Implementation

| Document | Description |
|---|---|
| [07_IMPLEMENTATION_PLAN.md](07_IMPLEMENTATION_PLAN.md) | 13-phase build plan with dependencies, file lists, steps, and exit criteria |
| [08_TEST_SPEC.md](08_TEST_SPEC.md) | pytest strategy, fixture hierarchy, mock boundaries, test scenarios per phase |
| [09_DEPLOYMENT_SPEC.md](09_DEPLOYMENT_SPEC.md) | Docker setup, port map, volume layout, development quickstart, production notes |
