"""Prove the backend container is isolated: internal services answer, the outside doesn't.

Run inside the backend container:
    docker compose exec backend python /app/scripts/check_isolation.py

Exits 0 only if every internal target is reachable and every external one is blocked.
Standard library only, so it also runs in a bare image.
"""

import socket
import sys

# (label, host, port)
MUST_REACH = [
    ("ollama", "ollama", 11434),
    ("chroma", "chroma", 8000),
]
MUST_BLOCK = [
    ("example.com (DNS + HTTPS)", "example.com", 443),
    ("1.1.1.1 (raw IP, no DNS needed)", "1.1.1.1", 443),
    ("host.docker.internal (host Ollama)", "host.docker.internal", 11434),
]


def can_connect(host: str, port: int, timeout: float = 3.0) -> bool:
    """True if a TCP connection opens. DNS failure, refusal and timeout all count as no."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run(
    must_reach: list[tuple[str, str, int]] = MUST_REACH,
    must_block: list[tuple[str, str, int]] = MUST_BLOCK,
    connect=can_connect,
) -> bool:
    ok = True
    for label, host, port in must_reach:
        reached = connect(host, port)
        ok &= reached
        print(f"{'PASS' if reached else 'FAIL'}  reachable  {label} ({host}:{port})")
    for label, host, port in must_block:
        blocked = not connect(host, port)
        ok &= blocked
        print(f"{'PASS' if blocked else 'FAIL'}  blocked    {label} ({host}:{port})")
    print("ISOLATED" if ok else "NOT ISOLATED")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
