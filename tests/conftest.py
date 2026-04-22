from pathlib import Path

import pytest


@pytest.fixture
def master_secret_env(monkeypatch):
    monkeypatch.setenv("EC2_MASTER_SECRET", "test-master-secret")


@pytest.fixture(autouse=True)
def _auto_master_secret(master_secret_env):
    # Ensure all tests run with deterministic server secret material.
    return None


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def sample_config_yaml(tmp_path: Path) -> Path:
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("fake-cert")
    key.write_text("fake-key")
    config = tmp_path / "config.yaml"
    config.write_text(f"""
server:
  host: "127.0.0.1"
  port: 4321
  data_dir: "{tmp_path / 'data'}"
  tls_cert: "{cert}"
  tls_key: "{key}"
operators:
  admin: "password123"
plugins:
  listeners:
    - "executec2.listeners.http_listener"
  agents:
    - "executec2.agents.python_agent"
logging:
  level: "DEBUG"
  format: "console"
""")
    return config
