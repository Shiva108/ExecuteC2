---
version: 1.0.0
date: 2026-03-17
project: ExecuteC2
language: Python 3.12+
---

# ExecuteC2 — Deployment Spec

## Docker Deployment

### Dockerfile (`docker/Dockerfile`)

```dockerfile
FROM python:3.12-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy source
COPY src/ src/
COPY agent/ agent/

# Create data directory
RUN mkdir -p /data

# Generate self-signed TLS cert if none provided
RUN openssl req -x509 -newkey rsa:2048 -keyout /app/default-key.pem \
    -out /app/default-cert.pem -days 365 -nodes \
    -subj "/CN=executec2"

EXPOSE 4321

ENTRYPOINT ["python", "-m", "executec2"]
CMD ["--config", "/app/config.yaml"]
```

### docker-compose.yml (`docker/docker-compose.yml`)

```yaml
version: "3.9"

services:
  teamserver:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    container_name: executec2
    ports:
      - "${EC2_PORT:-4321}:4321"
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - ec2-data:/data
      - ./certs:/app/certs:ro       # Optional: mount custom TLS certs
    environment:
      - EC2_DATA_DIR=/data
      - EC2_LOG_LEVEL=${EC2_LOG_LEVEL:-INFO}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('https://localhost:4321/api/auth/login', context=__import__('ssl').create_default_context())"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  ec2-data:
    driver: local
```

### Sample config.yaml for Docker

```yaml
server:
  host: "0.0.0.0"
  port: 4321
  data_dir: "/data"
  tls_cert: "/app/certs/cert.pem"    # Or /app/default-cert.pem
  tls_key: "/app/certs/key.pem"      # Or /app/default-key.pem

operators:
  admin: "changeme"

plugins:
  listeners:
    - "executec2.listeners.http_listener"
  agents:
    - "executec2.agents.python_agent"

logging:
  level: "INFO"
  format: "json"
```

## Port Map

| Port | Protocol | Purpose |
|---|---|---|
| 4321 | HTTPS | Teamserver REST API + WebSocket |
| (dynamic) | HTTP/S | Listener ports (configured per-listener) |
| (dynamic) | TCP | SOCKS5 proxy ports (configured per-tunnel) |
| (dynamic) | TCP | Local port forwarding (configured per-tunnel) |

Listener and tunnel ports must be published explicitly in `docker-compose.yml` `ports` section when using Docker, since they are dynamically configured.

## Volume Layout

| Path | Purpose |
|---|---|
| `/data/executec2.db` | SQLite database |
| `/data/downloads/` | Downloaded files from agents |
| `/app/config.yaml` | Server configuration (mounted) |
| `/app/certs/` | TLS certificates (mounted) |

## Development Setup

### Prerequisites

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Quick Start

```bash
# Clone and install
git clone <repo> && cd executec2
uv venv && uv pip install -e ".[dev]"

# Generate self-signed cert for development
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
    -days 365 -nodes -subj "/CN=localhost"

# Create config
cp docker/config.yaml config.yaml
# Edit config.yaml: set tls_cert/tls_key paths

# Run
uv run python -m executec2 --config config.yaml --debug

# Run tests
uv run pytest tests/ -v
```

### Dev Dependencies

```toml
# pyproject.toml [project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=6.0",
    "httpx>=0.28",
    "ruff>=0.9",
]
```

## Production Considerations

### TLS Certificates

- **Development:** Self-signed cert generated at build time or via `openssl`
- **Production:** Use certificates from a real CA or Let's Encrypt. Mount via Docker volume at `/app/certs/`.
- The teamserver will refuse to start without valid `tls_cert` and `tls_key` paths.

### Database Backups

SQLite WAL mode allows safe backup while the server is running:

```bash
# Hot backup using sqlite3 .backup command
docker exec executec2 sqlite3 /data/executec2.db ".backup /data/backup.db"
```

### Logging

In production, set `logging.format: "json"` for structured log ingestion. Logs are written to stdout by default (Docker-friendly). Optionally set `logging.file` for file output.

### Resource Limits

Recommended Docker resource constraints:

```yaml
services:
  teamserver:
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 512M
        reservations:
          cpus: "0.5"
          memory: 128M
```
