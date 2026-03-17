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

# Generate self-signed TLS cert for development use only.
# In production, mount real certs at /app/certs/ and reference them in config.yaml.
RUN openssl req -x509 -newkey rsa:2048 -keyout /app/default-key.pem \
    -out /app/default-cert.pem -days 365 -nodes \
    -subj "/CN=executec2"

EXPOSE 4321

ENTRYPOINT ["python", "-m", "executec2"]
CMD ["--config", "/app/config.yaml"]
