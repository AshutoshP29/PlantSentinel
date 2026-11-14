"""Live network view for the privacy panel: who is this process talking to, right now.

Everything here is read from the local kernel (psutil, /proc). Nothing is probed over the
network, so asking the question never creates the traffic it is looking for.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime
from pathlib import Path

import psutil

# Remote ports we know, so the panel can say what a connection is instead of a PID.
KNOWN_REMOTE_PORTS = {11434: "Models (Ollama)", 8000: "Vector store (Chroma)"}


def is_external(ip: str) -> bool:
    """True for an address outside this machine and its private/Docker networks."""
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return True  # unparseable remote: treat as outside, never hide it
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not (addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_unspecified)


def _raw_connections() -> list:
    try:
        return psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError):
        # Windows/macOS without admin: fall back to this process only.
        proc = psutil.Process()
        getter = getattr(proc, "net_connections", None) or proc.connections
        return getter(kind="inet")


def _process_label(pid: int | None, local_port: int, remote_port: int, api_port: int) -> str:
    if remote_port in KNOWN_REMOTE_PORTS and local_port != api_port:
        return KNOWN_REMOTE_PORTS[remote_port]
    if local_port == api_port:
        return "API (uvicorn)"
    if pid:
        try:
            return psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return "unknown"


def connections(api_port: int = 8000) -> list[dict]:
    """Established TCP connections as {local, remote, process, external}."""
    out = []
    for c in _raw_connections():
        if not c.raddr or c.status != psutil.CONN_ESTABLISHED:
            continue
        lip, lport = c.laddr[0], c.laddr[1]
        rip, rport = c.raddr[0], c.raddr[1]
        out.append(
            {
                "local": f"{lip}:{lport}",
                "remote": f"{rip}:{rport}",
                "process": _process_label(getattr(c, "pid", None), lport, rport, api_port),
                "external": is_external(rip),
            }
        )
    out.sort(key=lambda c: (not c["external"], c["process"], c["remote"]))
    return out


def has_default_route(route_table: Path = Path("/proc/net/route")) -> bool | None:
    """True if the kernel has a route off this network. None where /proc isn't available."""
    try:
        lines = route_table.read_text().splitlines()[1:]
    except OSError:
        return None
    return any(len(f := ln.split()) > 1 and f[1] == "00000000" for ln in lines)


def network_mode(in_container: bool | None = None, default_route: bool | None = None) -> str:
    """`isolated`: a container with no route out. `bridged`: a container that has one.
    `host`: not in a container, so isolation is whatever the host network allows."""
    if in_container is None:
        in_container = Path("/.dockerenv").exists()
    if not in_container:
        return "host"
    if default_route is None:
        default_route = has_default_route()
    return "bridged" if default_route else "isolated"


def snapshot(redactions: int = 0) -> dict:
    """The `PrivacyStatus` the frontend polls."""
    conns = connections()
    return {
        "external_connections": sum(c["external"] for c in conns),
        "network_mode": network_mode(),
        "redactions": redactions,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "connections": conns,
    }
