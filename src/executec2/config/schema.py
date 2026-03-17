from pathlib import Path

from pydantic import BaseModel, Field, field_validator


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
