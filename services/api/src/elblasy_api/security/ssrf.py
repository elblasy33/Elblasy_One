"""SSRF guard for user-supplied Odoo base URLs.

Validates scheme, credentials, port and every resolved IP. Callers that connect must
connect to a validated IP (or re-validate per redirect hop) to avoid DNS-rebinding gaps.
"""

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

Resolver = Callable[[str, int], list[str]]

_METADATA_NETS = [
    ipaddress.ip_network("169.254.0.0/16"),  # link-local incl. cloud metadata 169.254.169.254
    ipaddress.ip_network("fd00:ec2::/32"),  # AWS IPv6 metadata
]
_METADATA_HOSTS = {"metadata.google.internal", "metadata", "instance-data"}


class UnsafeUrlError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedUrl:
    url: str
    host: str
    port: int
    resolved_ips: tuple[str, ...]


def _default_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"host cannot be resolved: {host}") from exc
    return sorted({str(info[4][0]) for info in infos})


def validate_odoo_url(
    raw: str,
    *,
    production: bool,
    allow_private: bool = False,
    allow_insecure_http: bool = False,
    resolver: Resolver = _default_resolver,
) -> ValidatedUrl:
    parts = urlsplit(raw.strip())
    if parts.scheme not in ("http", "https"):
        raise UnsafeUrlError("only http(s) URLs are allowed")
    if parts.scheme == "http" and (production or not allow_insecure_http):
        raise UnsafeUrlError("HTTPS is required")
    if parts.username or parts.password:
        raise UnsafeUrlError("credentials in URL are not allowed")
    if not parts.hostname:
        raise UnsafeUrlError("missing host")
    if parts.query or parts.fragment:
        raise UnsafeUrlError("query/fragment not allowed in base URL")
    host = parts.hostname.lower().rstrip(".")
    if host in _METADATA_HOSTS:
        raise UnsafeUrlError("metadata endpoints are blocked")
    port = parts.port or (443 if parts.scheme == "https" else 80)

    ips = resolver(host, port)
    if not ips:
        raise UnsafeUrlError("host did not resolve")
    for ip_str in ips:
        ip = ipaddress.ip_address(ip_str)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if any(ip in net for net in _METADATA_NETS):
            raise UnsafeUrlError("metadata/link-local addresses are blocked")
        if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
            raise UnsafeUrlError("address not allowed")
        if (ip.is_private or ip.is_loopback) and not allow_private:
            raise UnsafeUrlError("private-network addresses are not allowed")
    base = f"{parts.scheme}://{host}" + (f":{parts.port}" if parts.port else "")
    base += parts.path.rstrip("/")
    return ValidatedUrl(url=base, host=host, port=port, resolved_ips=tuple(ips))
