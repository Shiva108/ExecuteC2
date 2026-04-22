from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class OperatorConfig(BaseModel):
    password: str
    roles: list[str] = Field(default_factory=list)


class ServerConfig(BaseModel):
    # Deprecated alias; retained for one release for compatibility.
    host: str = Field(default="0.0.0.0")
    admin_bind_host: str = Field(default="127.0.0.1")
    port: int = Field(default=4321, ge=1, le=65535)
    data_dir: Path = Field(default=Path("./data"))
    tls_cert: Path
    tls_key: Path
    operator_ui_origins: list[str] = Field(default_factory=list)
    access_token_ttl: int = Field(default=24, ge=1, description="Hours")
    refresh_token_ttl: int = Field(default=168, ge=1, description="Hours")
    auth_rate_limit: int = Field(default=10, ge=1, description="Requests per minute per IP")
    max_task_payload_bytes: int = Field(default=8 * 1024 * 1024, ge=1024)

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
    operators: dict[str, OperatorConfig] = Field(description="username -> operator credentials and roles")
    plugins: PluginConfig = Field(default_factory=PluginConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @field_validator("operators", mode="before")
    @classmethod
    def normalize_operators(cls, operators: dict) -> dict[str, dict]:
        normalized: dict[str, dict] = {}
        for username, value in operators.items():
            if isinstance(value, str):
                normalized[username] = {"password": value, "roles": ["admin"]}
                continue

            if isinstance(value, dict):
                password = value.get("password", "")
                roles = value.get("roles", ["operator"])
                normalized[username] = {"password": password, "roles": roles}
                continue

            raise ValueError(f"Invalid operator config for {username!r}")
        return normalized
