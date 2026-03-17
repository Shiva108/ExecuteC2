# You are tasked with writing and executing a comprehensive test suite for the ExecuteC2 teamserver project

## Context
ExecuteC2 is a Python/FastAPI/asyncio C2 teamserver. The project spec is in docs/ssd/, with the test spec at docs/ssd/08_TEST_SPEC.md and implementation plan at docs/ssd/07_IMPLEMENTATION_PLAN.md.

## Testing Stack

- pytest >= 8.3 with pytest-asyncio in `auto` mode
- httpx AsyncClient with ASGITransport for FastAPI testing
- In-memory SQLite (no mocks for DB, crypto, or event manager)
- Real FastAPI app via ASGI transport (no real sockets for unit tests)

## Your Tasks

### 1. Verify Project Structure
Check that the following exist and are importable:

- `src/executec2/__init__.py` with `__version__`
- `src/executec2/__main__.py` (CLI entry point)
- `src/executec2/server/app.py` with `create_app()`
- `src/executec2/server/database.py` with `Database` class
- `src/executec2/server/auth.py` with `JWTManager`, `OTPStore`, `RateLimiter`
- `src/executec2/server/broker.py` with `MessageBroker`
- `src/executec2/server/events.py` with `EventManager`
- `src/executec2/server/models.py` with all Pydantic models
- `src/executec2/listeners/base.py` with `ListenerPlugin` ABC
- `src/executec2/listeners/http_listener.py` with `HTTPListener`
- `src/executec2/agents/base.py` with `AgentPlugin` ABC
- `src/executec2/commands/registry.py` with `CommandRegistry`
- `src/executec2/tunnels/socks5.py` with SOCKS5 implementation
- `agent/main.py`, `agent/connector_http.py`, `agent/crypto.py`

### 2. Run Existing Tests
```bash
uv run pytest tests/ -v --tb=short 2>&1 | head -200
uv run pytest tests/ --cov --cov-report=term-missing 2>&1 | tail -50
```

### 3. Write Missing Tests
For any test files that don't exist yet, create them per the layout in docs/ssd/08_TEST_SPEC.md. Implement ALL test scenarios from each phase:

#### Phase 1 — Skeleton (tests/unit/test_models.py, conftest.py)

- `test_config_loads_valid_yaml` — load a sample config.yaml
- `test_config_rejects_missing_tls` — ValidationError without TLS paths
- `test_cli_help` — --help exits cleanly

#### Phase 2 — Database (tests/unit/test_database.py)

- `test_migrate_creates_all_tables` — all 8 tables exist
- `test_agent_crud_roundtrip` — insert → get → update → delete
- `test_task_cascade_delete` — delete agent cascades to tasks
- `test_credential_crud` — full CRUD lifecycle
- `test_wal_mode_enabled` — PRAGMA journal_mode = wal

#### Phase 3 — Auth (tests/unit/test_auth.py, tests/integration/test_api_auth.py)

- `test_login_valid_credentials`
- `test_login_invalid_password` — returns 401
- `test_refresh_token_rotation`
- `test_rate_limiting` — returns 429 after threshold
- `test_jwt_required_on_protected_routes` — 401 without token
- `test_otp_generation_and_consumption` — single-use OTP

#### Phase 4 — Events (tests/unit/test_events.py)

- `test_pre_hook_cancels_operation`
- `test_post_hook_executes_async`
- `test_hook_priority_ordering`
- `test_pre_hook_timeout`
- `test_multiple_hooks_same_event`

#### Phase 5 — WebSocket (tests/unit/test_broker.py, tests/integration/test_websocket.py)

- `test_websocket_sync_sequence` — SYNC_START → batches → SYNC_FINISH
- `test_subscription_filters_events`
- `test_backpressure_warning` — logged at 75% fill
- `test_state_message_dedup`

#### Phase 6 — Listener (tests/unit/test_http_listener.py, tests/integration/test_listener_api.py)

- `test_http_listener_starts_and_stops`
- `test_listener_config_validation`
- `test_decoy_page_for_non_agent`
- `test_listener_crud_api`
- `test_plugin_loader_discovers_http`

#### Phase 7 — Agent Framework (tests/unit/test_agent_lifecycle.py, tests/integration/test_agent_api.py)

- `test_agent_registration`
- `test_tick_updater_marks_inactive`
- `test_inactive_agent_reactivates`
- `test_agent_state_transitions`
- `test_agent_crud_api`

#### Phase 8 — Commands (tests/unit/test_commands.py)

- `test_command_registry_roundtrip`
- `test_all_builtin_commands_registered` — 19 commands for "python" agent type
- `test_command_execution_creates_task`
- `test_unknown_command_returns_400`
- `test_pre_hook_cancels_command`

#### Phase 9 — Agent Transport (tests/unit/test_agent_crypto.py, tests/integration/test_agent_checkin.py)

- `test_aes_gcm_roundtrip`
- `test_hkdf_key_derivation_deterministic`
- `test_agent_registration_flow`
- `test_agent_receives_and_executes_task`
- `test_agent_exponential_backoff`
- `test_kill_date_terminates_agent`

#### Phase 10 — Tasks (tests/unit/test_task_manager.py, tests/integration/test_task_lifecycle.py)

- `test_task_type_routing` — TASK/JOB/TUNNEL route to correct queue
- `test_task_cancellation`
- `test_job_progress_updates`
- `test_completed_task_stored_in_db`

#### Phase 11 — Tunneling (tests/unit/test_socks5.py, tests/integration/test_tunnel.py)

- `test_socks5_handshake_no_auth`
- `test_socks5_handshake_with_auth`
- `test_socks5_data_relay`
- `test_local_port_forward`
- `test_tunnel_stop_cleans_up`

#### Phase 12 — Credentials (tests/unit/test_credentials.py, tests/unit/test_targets.py, tests/integration/test_credential_api.py)

- `test_credential_at_rest_encryption`
- `test_credential_crud_api`
- `test_target_crud_api`
- `test_credential_event_broadcast`
- `test_chat_message`

### 4. Use the Correct Fixture Hierarchy
All tests must use the fixtures from docs/ssd/08_TEST_SPEC.md:
```
db (in-memory SQLite) → app (FastAPI) → client (httpx) → auth_client (JWT) → ws_client
```

### 5. Categorize Results
After running the full suite, produce a report with:

- **PASS** count per phase
- **FAIL** count per phase with root cause (missing implementation vs. broken logic)
- **SKIP/ERROR** count (missing imports = phase not implemented)
- Overall coverage percentage
- Which phases are fully implemented, partially implemented, or not started

### 6. Fix Test Bugs (not implementation bugs)
If a test fails due to a test-writing error (wrong fixture name, import path typo, wrong HTTP method), fix the test. Do NOT fix or add implementation code — only note what implementation is missing.

### 7. Coverage Targets

- Server core: 80%+ (fail if below)
- Agent payload: 60%+ (warn if below)
- Overall: 70%+ (fail_under per pyproject.toml)

## Acceptance Criteria

- All test files exist per the layout in docs/ssd/08_TEST_SPEC.md
- All tests for implemented phases pass
- Tests for unimplemented phases are written but skip with `pytest.skip("Phase N not yet implemented")` or are collected as expected failures
- Coverage report generated
- Summary report of implementation status by phase
