.PHONY: help install test test-unit test-integration cov lint fmt run clean

# Default target
help:
	@echo "ExecuteC2 — available targets:"
	@echo ""
	@echo "  install        Install project + dev dependencies"
	@echo "  test           Run all tests"
	@echo "  test-unit      Run unit tests only"
	@echo "  test-int       Run integration tests only"
	@echo "  cov            Run tests with coverage report"
	@echo "  lint           Lint with ruff"
	@echo "  fmt            Format with ruff"
	@echo "  run            Start the teamserver (requires config.yaml)"
	@echo "  cert           Generate a self-signed dev TLS certificate"
	@echo "  clean          Remove build artefacts and caches"

install:
	uv pip install -e ".[dev]"

test:
	uv run pytest tests/

test-unit:
	uv run pytest tests/unit/

test-int:
	uv run pytest tests/integration/

cov:
	uv run pytest --cov --cov-report=term-missing

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

run:
	uv run python -m executec2 --config config.yaml

# Generate a self-signed TLS cert for development (outputs cert.pem + key.pem)
cert:
	openssl req -x509 -newkey rsa:2048 \
	  -keyout key.pem -out cert.pem \
	  -days 365 -nodes -subj "/CN=executec2"
	@echo "Generated cert.pem and key.pem (development only — gitignored)"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ .coverage htmlcov/ .pytest_cache/ .ruff_cache/
