"""Compatibility checks between ingress chains and traffic profiles."""

from __future__ import annotations

from executec2.server.models import (
    InfrastructureAssetData,
    InfrastructureAssetType,
    TrafficProfileData,
    TrafficProfileTLSMode,
)


class IncompatibleProfileError(ValueError):
    """Raised when a traffic profile cannot be attached to an ingress chain."""


def validate_profile_compatibility(
    profile: TrafficProfileData,
    chain: list[InfrastructureAssetData],
    *,
    port_bind: int,
) -> None:
    hostnames = set()
    tls_capable = False
    blocked_request_headers: set[str] = set()
    blocked_response_headers: set[str] = set()
    preserves_host_header = True
    explicit_origin_ports: set[int] = set()

    for asset in chain:
        hostname = str(asset.config.get("hostname", "")) or asset.name
        if asset.asset_type in {InfrastructureAssetType.DOMAIN, InfrastructureAssetType.CDN_EDGE}:
            hostnames.add(hostname)
        if asset.asset_type is InfrastructureAssetType.CERTIFICATE:
            tls_capable = True
            if hostname:
                hostnames.add(hostname)
        if bool(asset.config.get("tls_termination")):
            tls_capable = True

        raw_origin_ports = asset.config.get("origin_ports", [])
        if isinstance(raw_origin_ports, list):
            explicit_origin_ports.update(
                int(port) for port in raw_origin_ports if str(port).isdigit()
            )

        blocked_request_headers.update(
            header.lower() for header in asset.config.get("blocked_request_headers", [])
        )
        blocked_response_headers.update(
            header.lower() for header in asset.config.get("blocked_response_headers", [])
        )
        if asset.config.get("preserve_host_header") is False:
            preserves_host_header = False

    required_hosts = set(profile.host_headers) | set(profile.callback_hostnames)
    if required_hosts and not required_hosts.issubset(hostnames):
        missing = sorted(required_hosts - hostnames)
        raise IncompatibleProfileError(
            f"Ingress chain is missing required hostnames: {', '.join(missing)}"
        )

    if profile.tls_mode is TrafficProfileTLSMode.REQUIRED and not tls_capable:
        raise IncompatibleProfileError("TLS-required profile needs a certificate or TLS terminator")

    if explicit_origin_ports and port_bind and port_bind not in explicit_origin_ports:
        allowed = ", ".join(str(port) for port in sorted(explicit_origin_ports))
        raise IncompatibleProfileError(
            f"Ingress chain origin ports {allowed} do not permit listener port {port_bind}"
        )

    if not preserves_host_header and profile.host_headers:
        raise IncompatibleProfileError("Ingress chain cannot preserve required host headers")

    required_request_headers = {
        header.lower() for header, value in profile.request_headers.items() if value != ""
    }
    required_response_headers = {
        header.lower() for header, value in profile.response_headers.items() if value != ""
    }
    if blocked_request_headers & required_request_headers:
        blocked = ", ".join(sorted(blocked_request_headers & required_request_headers))
        raise IncompatibleProfileError(f"Ingress chain blocks required request headers: {blocked}")
    if blocked_response_headers & required_response_headers:
        blocked = ", ".join(sorted(blocked_response_headers & required_response_headers))
        raise IncompatibleProfileError(f"Ingress chain blocks required response headers: {blocked}")
