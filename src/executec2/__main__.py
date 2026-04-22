import argparse
import os
import sys
from pathlib import Path

import yaml

from executec2 import __version__


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="executec2",
        description="ExecuteC2 Teamserver",
    )
    parser.add_argument(
        "--config", "-c",
        default=os.environ.get("EC2_CONFIG", "config.yaml"),
        help="Path to config.yaml (default: config.yaml)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=os.environ.get("EC2_DEBUG", "").lower() in ("1", "true", "yes"),
        help="Enable debug logging",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("EC2_HOST"),
        help="Override management bind address",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=int(os.environ.get("EC2_PORT", 0)) or None,
        help="Override listen port",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    # Apply env var overrides
    if os.environ.get("EC2_DATA_DIR"):
        raw.setdefault("server", {})["data_dir"] = os.environ["EC2_DATA_DIR"]
    if os.environ.get("EC2_TLS_CERT"):
        raw.setdefault("server", {})["tls_cert"] = os.environ["EC2_TLS_CERT"]
    if os.environ.get("EC2_TLS_KEY"):
        raw.setdefault("server", {})["tls_key"] = os.environ["EC2_TLS_KEY"]
    if os.environ.get("EC2_LOG_LEVEL"):
        raw.setdefault("logging", {})["level"] = os.environ["EC2_LOG_LEVEL"]

    # Apply CLI overrides
    if args.host:
        raw.setdefault("server", {})["admin_bind_host"] = args.host
    if args.port:
        raw.setdefault("server", {})["port"] = args.port
    if args.debug:
        raw.setdefault("logging", {})["level"] = "DEBUG"

    # Backward compatibility: support deprecated server.host alias.
    server_cfg = raw.setdefault("server", {})
    if "admin_bind_host" not in server_cfg and "host" in server_cfg:
        server_cfg["admin_bind_host"] = server_cfg["host"]

    from executec2.config.schema import ExecuteC2Config
    config = ExecuteC2Config.model_validate(raw)

    import asyncio

    from executec2.server.app import run_server
    asyncio.run(run_server(config))


if __name__ == "__main__":
    main()
