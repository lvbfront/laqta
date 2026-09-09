from __future__ import annotations

import ipaddress

from fastapi import Request


def client_ip(request: Request) -> str | None:
    """request.client.host as a validated IP string, or None.

    Not always a real IP: absent behind some proxy configs, and (what
    surfaced this) Starlette's TestClient sends the literal string
    "testclient" -- either would raise if handed directly to a Postgres
    INET column (guests.consent_ip, downloads.ip), so validate first and
    fall back to None rather than letting consent capture/download
    logging fail outright over an unparseable IP.
    """
    if request.client is None:
        return None
    host = request.client.host
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return None
    return host
