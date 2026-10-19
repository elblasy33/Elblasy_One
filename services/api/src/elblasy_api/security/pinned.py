"""An XML-RPC transport that connects to an IP address that was already validated.

`validate_odoo_url` resolves the host and checks every address. If the HTTP client then resolved the
name again, an attacker-controlled DNS server could answer differently the second time (DNS
rebinding) and steer the request to an internal address. Connecting to the validated IP closes that
gap; the original host name is still used for the Host header and for TLS (SNI + certificate check)."""

import http.client
import socket
import ssl
import xmlrpc.client


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host: str, ip: str, **kw: object) -> None:
        super().__init__(host, **kw)  # type: ignore[arg-type]
        self._pinned_ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, **kw: object) -> None:
        super().__init__(host, **kw)  # type: ignore[arg-type]
        self._pinned_ip = ip

    def connect(self) -> None:
        raw = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        ctx = self._context if hasattr(self, "_context") else ssl.create_default_context()
        self.sock = ctx.wrap_socket(
            raw, server_hostname=self.host
        )  # verifies the certificate for the NAME


class PinnedTransport(xmlrpc.client.Transport):
    def __init__(self, ip: str, https: bool, timeout: float) -> None:
        super().__init__()
        self._ip, self._https, self._timeout = ip, https, timeout

    def make_connection(self, host: str | tuple[str, dict[str, str]]) -> http.client.HTTPConnection:
        cached = self._connection
        if cached and host == cached[0]:
            conn_cached = cached[1]
            if conn_cached is not None:
                return conn_cached
        chost, self._extra_headers, _ = self.get_host_info(host)
        conn: http.client.HTTPConnection = (
            _PinnedHTTPS(chost, self._ip, timeout=self._timeout)
            if self._https
            else _PinnedHTTP(chost, self._ip, timeout=self._timeout)
        )
        self._connection = host, conn
        return conn
