from pathlib import Path

import pytest
from pydantic import ValidationError

from executec2.config.schema import ExecuteC2Config, LoggingConfig, PluginConfig, ServerConfig


def test_server_config_defaults():
    cfg = ServerConfig(tls_cert=Path("/tmp/cert.pem"), tls_key=Path("/tmp/key.pem"))
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 4321
    assert cfg.access_token_ttl == 24
    assert cfg.refresh_token_ttl == 168
    assert cfg.auth_rate_limit == 10


def test_server_config_port_bounds():
    with pytest.raises(ValidationError):
        ServerConfig(port=0, tls_cert=Path("/tmp/cert.pem"), tls_key=Path("/tmp/key.pem"))
    with pytest.raises(ValidationError):
        ServerConfig(port=70000, tls_cert=Path("/tmp/cert.pem"), tls_key=Path("/tmp/key.pem"))


def test_plugin_config_defaults():
    cfg = PluginConfig()
    assert cfg.listeners == []
    assert cfg.agents == []


def test_logging_config_defaults():
    cfg = LoggingConfig()
    assert cfg.level == "INFO"
    assert cfg.format == "json"
    assert cfg.file == ""


def test_full_config_from_yaml(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("fake")
    key.write_text("fake")
    data_dir = tmp_path / "data"

    raw = {
        "server": {
            "host": "127.0.0.1",
            "port": 4321,
            "data_dir": str(data_dir),
            "tls_cert": str(cert),
            "tls_key": str(key),
        },
        "operators": {"admin": "secret"},
        "plugins": {
            "listeners": ["executec2.listeners.http_listener"],
            "agents": ["executec2.agents.python_agent"],
        },
        "logging": {"level": "DEBUG", "format": "console"},
    }
    config = ExecuteC2Config.model_validate(raw)
    assert config.server.host == "127.0.0.1"
    assert config.server.port == 4321
    assert config.operators == {"admin": "secret"}
    assert "executec2.listeners.http_listener" in config.plugins.listeners
    assert config.logging.level == "DEBUG"
    assert data_dir.exists()


def test_config_missing_tls_fails():
    with pytest.raises(ValidationError):
        ExecuteC2Config.model_validate({
            "server": {"host": "0.0.0.0", "port": 4321},
            "operators": {"admin": "pass"},
        })


def test_cli_help():
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-m", "executec2", "--help"],
        capture_output=True,
        cwd=Path(__file__).parent.parent.parent,
    )
    assert result.returncode == 0
    assert b"executec2" in result.stdout.lower() or b"usage" in result.stdout.lower()
