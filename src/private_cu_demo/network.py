import ipaddress
import socket
from urllib.parse import urlsplit

from .errors import DemoError

PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(prefix)
    for prefix in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
)


def resolve_private(endpoint: str) -> list[str]:
    hostname = urlsplit(endpoint).hostname
    if not hostname:
        raise DemoError("The endpoint has no hostname.")
    try:
        records = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DemoError(f"Cannot resolve {hostname}; check private DNS links.") from exc
    addresses = sorted({str(record[4][0]) for record in records})
    if not addresses:
        raise DemoError(f"No DNS addresses returned for {hostname}.")
    for value in addresses:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if not any(address in network for network in PRIVATE_NETWORKS):
            raise DemoError(
                f"{hostname} resolves to non-private address {value}. "
                "Run inside the VNet and correct private DNS; public fallback is disabled."
            )
    return addresses


def diagnose_endpoints(endpoints: dict[str, str]) -> dict[str, object]:
    report: dict[str, object] = {}
    failures: list[str] = []
    for name, endpoint in endpoints.items():
        try:
            addresses = resolve_private(endpoint)
            for address in addresses:
                with socket.create_connection((address, 443), timeout=5):
                    pass
            report[name] = {"addresses": addresses, "tcp_443": True}
        except (DemoError, OSError) as exc:
            report[name] = {"error": str(exc), "tcp_443": False}
            failures.append(name)
    report["ok"] = not failures
    report["failed_endpoints"] = failures
    return report
